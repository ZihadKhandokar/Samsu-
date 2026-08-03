from typing import Any, Callable

from agent.project_planner import ProjectPlanner
from agent.state import WorkspaceAgentState


def make_plan_project_node(
    planner: ProjectPlanner,
) -> Callable[[WorkspaceAgentState], dict[str, Any]]:
    def plan_project(state: WorkspaceAgentState) -> dict[str, Any]:
        if state.get("planned_files"):
            return {}

        phase_plan = planner.plan(
            request=state["request"],
            project_root=state.get("project_root", ""),
            phase_number=state.get("phase_number", 1),
            phase_file_limit=state.get("phase_file_limit", 6),
            completed_files=state.get("completed_files", []),
        )
        return {
            "planned_files": phase_plan["files"],
            "phase_title": phase_plan["phase_title"],
            "has_more": phase_plan["has_more"],
            "next_phase": phase_plan["next_phase"],
            "current_file_index": 0,
            "created_files": [],
            "updated_files": [],
            "failed_files": [],
            "permission_approved": False,
            "status": "waiting_for_permission",
            "error": None,
            "summary": None,
        }

    return plan_project
