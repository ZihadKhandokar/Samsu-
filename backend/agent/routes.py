from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from agent.graph import WorkspaceAgentRuntime


class AgentTaskRequest(BaseModel):
    user_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    request: str = Field(min_length=3)
    project_root: str = ""
    phase_number: int = Field(default=1, ge=1, le=100)
    phase_file_limit: int = Field(default=6, ge=2, le=10)
    completed_files: list[str] = Field(default_factory=list, max_length=500)


class AgentDecisionRequest(BaseModel):
    approved: bool


class WorkspaceAgentService:
    """Runs slow local-model jobs outside FastAPI request threads."""

    def __init__(self, runtime: WorkspaceAgentRuntime):
        self.runtime = runtime
        # A local llama.cpp server should normally process one generation at a time.
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="samsu-agent")
        self.jobs: dict[str, Future[dict[str, Any]]] = {}
        self.phases: dict[str, str] = {}
        self.lock = Lock()

    def start(self, body: AgentTaskRequest) -> dict[str, Any]:
        task_id = uuid4().hex
        future = self.executor.submit(
            self.runtime.start,
            body.user_id,
            body.conversation_id,
            body.request,
            body.project_root,
            task_id,
            body.phase_number,
            body.phase_file_limit,
            body.completed_files,
        )
        with self.lock:
            self.jobs[task_id] = future
            self.phases[task_id] = "planning"
        return {"task_id": task_id, "status": "planning", "poll": f"/agent/tasks/{task_id}"}

    def decide(self, task_id: str, approved: bool) -> dict[str, Any]:
        current = self.get(task_id)
        if current.get("status") in {"planning", "running"}:
            raise RuntimeError("The current agent step has not finished yet.")
        if not current.get("requires_approval"):
            raise RuntimeError("This task is not waiting for approval.")
        future = self.executor.submit(self.runtime.resume, task_id, approved)
        with self.lock:
            self.jobs[task_id] = future
            self.phases[task_id] = "running" if approved else "cancelling"
        return {"task_id": task_id, "status": self.phases[task_id], "poll": f"/agent/tasks/{task_id}"}

    def get(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            future = self.jobs.get(task_id)
            phase = self.phases.get(task_id)
        if future is not None and not future.done():
            return {"task_id": task_id, "status": phase or "running", "requires_approval": False}
        if future is not None:
            try:
                result = future.result()
            except Exception as error:
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "requires_approval": False,
                    "error": str(error),
                }
            with self.lock:
                self.phases[task_id] = str(result.get("status", "unknown"))
            return result
        return self.runtime.get(task_id)

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)


def create_agent_router(service: WorkspaceAgentService) -> APIRouter:
    router = APIRouter(prefix="/agent", tags=["workspace-agent"])

    @router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
    async def start_task(body: AgentTaskRequest) -> dict[str, Any]:
        return service.start(body)

    @router.post(
        "/tasks/{task_id}/decision",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def decide_task(
        task_id: str,
        body: AgentDecisionRequest,
    ) -> dict[str, Any]:
        try:
            return service.decide(task_id, body.approved)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, Any]:
        try:
            return service.get(task_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return router
