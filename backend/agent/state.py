from typing import Any, TypedDict


class PlannedFile(TypedDict, total=False):
    path: str
    purpose: str
    operation: str
    dependencies: list[str]


class WorkspaceAgentState(TypedDict, total=False):
    task_id: str
    user_id: str
    conversation_id: str
    request: str
    project_root: str
    phase_number: int
    phase_file_limit: int
    completed_files: list[str]
    phase_title: str | None
    has_more: bool
    next_phase: str | None
    planned_files: list[PlannedFile]
    current_file_index: int
    current_file: PlannedFile | None
    current_payload: Any
    current_save_result: dict[str, Any] | None
    created_files: list[str]
    updated_files: list[str]
    failed_files: list[dict[str, Any]]
    permission_approved: bool
    status: str
    error: str | None
    summary: str | None
