from typing import Any

from langgraph.types import interrupt

from agent.state import WorkspaceAgentState


def request_permission(state: WorkspaceAgentState) -> dict[str, Any]:
    files = [
        {
            "path": item["path"],
            "purpose": item.get("purpose", "Project file"),
            "operation": item.get("operation", "create"),
        }
        for item in state.get("planned_files", [])
    ]
    decision = interrupt(
        {
            "type": "project_file_plan",
            "task_id": state["task_id"],
            "phase_number": state.get("phase_number", 1),
            "phase_title": state.get("phase_title") or "Project phase",
            "message": "Review the complete file plan before Samsu++ writes it.",
            "project_root": state.get("project_root", ""),
            "files": files,
        }
    )

    if isinstance(decision, dict):
        approved = bool(decision.get("approved"))
    else:
        approved = bool(decision)

    return {
        "permission_approved": approved,
        "status": "running" if approved else "cancelled",
        "summary": None if approved else "The project file plan was rejected.",
    }
