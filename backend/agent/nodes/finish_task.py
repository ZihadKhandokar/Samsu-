from typing import Any

from agent.state import WorkspaceAgentState


def finish_task(state: WorkspaceAgentState) -> dict[str, Any]:
    if state.get("status") == "cancelled":
        return {"summary": state.get("summary") or "The task was cancelled."}

    created = state.get("created_files", [])
    updated = state.get("updated_files", [])
    failed = state.get("failed_files", [])
    if failed or state.get("error"):
        failure_details = []
        for failure in failed:
            path = failure.get("path", "unknown file")
            stage = failure.get("stage", "processing")
            error = failure.get("error", "Unknown error")
            failure_details.append(f"{path} [{stage}]: {error}")

        details = "; ".join(failure_details)
        if not details:
            details = state.get("error") or "Unknown file-processing error."

        return {
            "status": "failed",
            "summary": (
                f"Stopped after creating {len(created)} and updating "
                f"{len(updated)} files. Failed: {details}"
            ),
        }
    return {
        "status": "completed",
        "summary": (
            f"Completed {state.get('phase_title') or 'this phase'}: created "
            f"{len(created)} file(s) and updated {len(updated)} file(s)."
        ),
    }
