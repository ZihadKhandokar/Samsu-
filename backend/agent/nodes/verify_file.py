from typing import Any, Callable

from agent.nodes.generate_file import _project_path
from agent.state import WorkspaceAgentState
from files.workspace_manager import WorkspaceManager


def make_verify_file_node(
    workspace: WorkspaceManager,
) -> Callable[[WorkspaceAgentState], dict[str, Any]]:
    def verify_file(state: WorkspaceAgentState) -> dict[str, Any]:
        file_spec = state.get("current_file")
        if not file_spec:
            raise RuntimeError("No saved file is ready to verify.")
        relative_path = _project_path(
            state.get("project_root", ""),
            file_spec["path"],
        )
        try:
            verification = workspace.verify_file(relative_path)
        except Exception as error:
            failed = list(state.get("failed_files", []))
            failed.append({"path": relative_path, "stage": "verify", "error": str(error)})
            return {
                "current_file_index": state.get("current_file_index", 0) + 1,
                "current_payload": None,
                "failed_files": failed,
                "status": "running",
                "error": str(error),
            }
        save_result = dict(state.get("current_save_result") or {})
        save_result["verification"] = verification
        return {
            "current_file_index": state.get("current_file_index", 0) + 1,
            "current_payload": None,
            "current_save_result": save_result,
            "status": "running",
            "error": None,
        }

    return verify_file
