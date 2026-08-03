from typing import Any, Callable

from agent.file_generator import FileGenerator
from agent.state import WorkspaceAgentState
from files.workspace_manager import WorkspaceManager


def make_generate_file_node(
    generator: FileGenerator,
    workspace: WorkspaceManager,
) -> Callable[[WorkspaceAgentState], dict[str, Any]]:
    def generate_file(state: WorkspaceAgentState) -> dict[str, Any]:
        index = state.get("current_file_index", 0)
        files = state.get("planned_files", [])
        if index >= len(files):
            return {"status": "finishing"}

        file_spec = files[index]
        relative_path = _project_path(
            state.get("project_root", ""),
            file_spec["path"],
        )
        # Resolving before generation rejects unsafe model-produced paths.
        target = workspace.resolve(relative_path)
        existing = workspace.read_file(relative_path) if target.is_file() else None
        try:
            payload = generator.generate(
                request=state["request"],
                project_root=state.get("project_root", ""),
                file_spec=file_spec,
            completed_files=(
                state.get("completed_files", [])
                + state.get("created_files", [])
                + state.get("updated_files", [])
            ),
                existing=existing,
            )
        except Exception as error:
            failed = list(state.get("failed_files", []))
            failed.append({"path": relative_path, "stage": "generate", "error": str(error)})
            return {
                "current_file": file_spec,
                "current_payload": None,
                "current_file_index": index + 1,
                "failed_files": failed,
                "status": "running",
                "error": str(error),
            }
        return {
            "current_file": file_spec,
            "current_payload": payload,
            "current_save_result": None,
            "status": "saving",
            "error": None,
        }

    return generate_file


def _project_path(project_root: str, file_path: str) -> str:
    parts = [part.strip("/\\") for part in (project_root, file_path) if part]
    return "/".join(part for part in parts if part)
