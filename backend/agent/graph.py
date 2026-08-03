from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agent.file_generator import FileGenerator
from agent.nodes.finish_task import finish_task
from agent.nodes.generate_file import make_generate_file_node
from agent.nodes.plan_project import make_plan_project_node
from agent.nodes.request_permission import request_permission
from agent.nodes.save_file import make_save_file_node
from agent.nodes.verify_file import make_verify_file_node
from agent.project_planner import ProjectPlanner
from agent.state import WorkspaceAgentState
from files.workspace_manager import WorkspaceManager


def build_graph(
    workspace: WorkspaceManager,
    planner: ProjectPlanner,
    generator: FileGenerator,
) -> StateGraph:
    graph = StateGraph(WorkspaceAgentState)
    graph.add_node("plan_project", make_plan_project_node(planner))
    graph.add_node("request_permission", request_permission)
    graph.add_node("generate_file", make_generate_file_node(generator, workspace))
    graph.add_node("save_file", make_save_file_node(workspace))
    graph.add_node("verify_file", make_verify_file_node(workspace))
    graph.add_node("finish_task", finish_task)

    graph.add_edge(START, "plan_project")
    graph.add_edge("plan_project", "request_permission")
    graph.add_conditional_edges(
        "request_permission",
        _after_permission,
        {"generate_file": "generate_file", "finish_task": "finish_task"},
    )
    graph.add_conditional_edges(
        "generate_file",
        _after_generation,
        {
            "save_file": "save_file",
            "generate_file": "generate_file",
            "finish_task": "finish_task",
        },
    )
    graph.add_conditional_edges(
        "save_file",
        _after_save,
        {"verify_file": "verify_file", "generate_file": "generate_file", "finish_task": "finish_task"},
    )
    graph.add_conditional_edges(
        "verify_file",
        _after_verification,
        {"generate_file": "generate_file", "finish_task": "finish_task"},
    )
    graph.add_edge("finish_task", END)
    return graph


def _after_permission(state: WorkspaceAgentState) -> str:
    return "generate_file" if state.get("permission_approved") else "finish_task"


def _after_verification(state: WorkspaceAgentState) -> str:
    return (
        "generate_file"
        if state.get("current_file_index", 0) < len(state.get("planned_files", []))
        else "finish_task"
    )


def _after_generation(state: WorkspaceAgentState) -> str:
    if state.get("current_payload") is not None:
        return "save_file"
    return _next_file_or_finish(state)


def _after_save(state: WorkspaceAgentState) -> str:
    if state.get("current_save_result") and state.get("current_payload") is not None:
        return "verify_file"
    return _next_file_or_finish(state)


def _next_file_or_finish(state: WorkspaceAgentState) -> str:
    return (
        "generate_file"
        if state.get("current_file_index", 0) < len(state.get("planned_files", []))
        else "finish_task"
    )


class WorkspaceAgentRuntime:
    """Persistent runner. Create one instance during FastAPI startup."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        planner: ProjectPlanner,
        generator: FileGenerator,
        checkpoint_path: str | Path,
    ):
        checkpoint = Path(checkpoint_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
        self._checkpointer_context = SqliteSaver.from_conn_string(str(checkpoint))
        self._checkpointer = self._checkpointer_context.__enter__()
        self._app = build_graph(workspace, planner, generator).compile(
            checkpointer=self._checkpointer
        )

    @staticmethod
    def _config(task_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": task_id}}

    def start(
        self,
        user_id: str,
        conversation_id: str,
        request: str,
        project_root: str = "",
        task_id: str | None = None,
        phase_number: int = 1,
        phase_file_limit: int = 6,
        completed_files: list[str] | None = None,
    ) -> dict[str, Any]:
        task_id = task_id or uuid4().hex
        initial: WorkspaceAgentState = {
            "task_id": task_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "request": request,
            "project_root": project_root.strip("/\\"),
            "phase_number": max(1, int(phase_number)),
            "phase_file_limit": min(max(int(phase_file_limit), 2), 10),
            "completed_files": list(completed_files or []),
            "has_more": False,
            "status": "planning",
            "created_files": [],
            "updated_files": [],
            "failed_files": [],
        }
        result = self._app.invoke(initial, config=self._config(task_id))
        return self._response(task_id, result)

    def resume(self, task_id: str, approved: bool) -> dict[str, Any]:
        result = self._app.invoke(
            Command(resume={"approved": approved}),
            config=self._config(task_id),
        )
        return self._response(task_id, result)

    def stream_start(
        self,
        user_id: str,
        conversation_id: str,
        request: str,
        project_root: str = "",
        task_id: str | None = None,
        phase_number: int = 1,
        phase_file_limit: int = 6,
        completed_files: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        task_id = task_id or uuid4().hex
        initial: WorkspaceAgentState = {
            "task_id": task_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "request": request,
            "project_root": project_root.strip("/\\"),
            "phase_number": max(1, int(phase_number)),
            "phase_file_limit": min(max(int(phase_file_limit), 2), 10),
            "completed_files": list(completed_files or []),
            "has_more": False,
            "status": "planning",
            "created_files": [],
            "updated_files": [],
            "failed_files": [],
        }
        for update in self._app.stream(
            initial,
            config=self._config(task_id),
            stream_mode="updates",
        ):
            yield {"task_id": task_id, "update": update}

    def get(self, task_id: str) -> dict[str, Any]:
        snapshot = self._app.get_state(self._config(task_id))
        state = dict(snapshot.values or {})
        if snapshot.interrupts:
            state["__interrupt__"] = list(snapshot.interrupts)
        return self._response(task_id, state)

    @staticmethod
    def _response(task_id: str, state: dict[str, Any]) -> dict[str, Any]:
        state = dict(state)
        interrupts = state.pop("__interrupt__", []) or []
        return {
            "task_id": task_id,
            "status": state.get("status", "unknown"),
            "state": state,
            "requires_approval": bool(interrupts),
            "interrupts": [getattr(item, "value", item) for item in interrupts],
        }

    def close(self) -> None:
        self._checkpointer_context.__exit__(None, None, None)
