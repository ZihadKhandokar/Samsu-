from typing import Any, Callable

from agent.nodes.generate_file import _project_path
from agent.state import WorkspaceAgentState
from files.workspace_manager import WorkspaceManager


def make_save_file_node(
    workspace: WorkspaceManager,
) -> Callable[[WorkspaceAgentState], dict[str, Any]]:
    def save_file(state: WorkspaceAgentState) -> dict[str, Any]:
        file_spec = state.get("current_file")
        if not file_spec:
            raise RuntimeError("No generated file is ready to save.")

        relative_path = _project_path(
            state.get("project_root", ""),
            file_spec["path"],
        )
        existed = workspace.resolve(relative_path).is_file()
        try:
            result = workspace.write_file(
                relative_path=relative_path,
                payload=state.get("current_payload"),
                overwrite=existed,
                operation="agent_update" if existed else "agent_create",
            )
        except Exception as error:
            failed = list(state.get("failed_files", []))
            failed.append({"path": relative_path, "stage": "save", "error": str(error)})
            return {
                "current_file_index": state.get("current_file_index", 0) + 1,
                "current_payload": None,
                "failed_files": failed,
                "status": "running",
                "error": str(error),
            }
        created = list(state.get("created_files", []))
        updated = list(state.get("updated_files", []))
        (updated if existed else created).append(relative_path)
        return {
            "created_files": created,
            "updated_files": updated,
            "current_save_result": result,
            "status": "verifying",
            "error": None,
        }

    return save_file
