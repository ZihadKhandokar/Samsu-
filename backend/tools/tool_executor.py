import difflib
from typing import Any

from config import settings
from tools.approval_manager import ApprovalManager
from tools.file_manager import FileManager


class ToolExecutor:
    SAFE_OPERATIONS = {
        "list_directory",
        "read_file",
        "search_files",
        "file_info",
    }

    MUTATING_OPERATIONS = {
        "write_file",
        "edit_file",
        "rename_file",
        "delete_file",
    }

    def __init__(self):
        self.file_manager = FileManager(
            workspace_root=(
                settings.FILE_WORKSPACE_ROOT
            ),
            allowed_extensions=(
                settings.ALLOWED_FILE_EXTENSIONS
            ),
            max_file_size_bytes=(
                settings.MAX_FILE_SIZE_BYTES
            ),
            database_path=(
                settings.DATABASE_PATH
            ),
        )

        self.approvals = ApprovalManager(
            database_path=(
                settings.DATABASE_PATH
            ),
            expiration_minutes=10,
        )

    def request(
        self,
        operation: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if operation in self.SAFE_OPERATIONS:
            result = self._execute_safe(
                operation,
                arguments,
            )

            return {
                "status": "completed",
                "operation": operation,
                "result": result,
            }

        if operation in self.MUTATING_OPERATIONS:
            preview = self._create_preview(
                operation,
                arguments,
            )

            approval = self.approvals.create(
                action=operation,
                payload=arguments,
                preview=preview,
            )

            return {
                "status": "approval_required",
                "operation": operation,
                "approval": approval,
            }

        raise ValueError(
            f"Unsupported operation: {operation}"
        )

    def _execute_safe(
        self,
        operation: str,
        arguments: dict[str, Any],
    ) -> Any:
        if operation == "list_directory":
            return (
                self.file_manager
                .list_directory(
                    relative_path=arguments.get(
                        "path",
                        "",
                    )
                )
            )

        if operation == "read_file":
            return (
                self.file_manager
                .read_file(
                    relative_path=arguments[
                        "path"
                    ]
                )
            )

        if operation == "file_info":
            return (
                self.file_manager
                .file_info(
                    relative_path=arguments[
                        "path"
                    ]
                )
            )

        if operation == "search_files":
            return (
                self.file_manager
                .search_files(
                    query=arguments["query"],
                    search_content=arguments.get(
                        "search_content",
                        True,
                    ),
                    limit=arguments.get(
                        "limit",
                        50,
                    ),
                )
            )

        raise ValueError(
            f"Unsupported safe operation: {operation}"
        )

    def _create_preview(
        self,
        operation: str,
        arguments: dict[str, Any],
    ) -> str:
        if operation == "write_file":
            path = arguments["path"]
            new_content = arguments["content"]

            if self.file_manager.exists(path):
                old_content = (
                    self.file_manager
                    .read_file(path)["content"]
                )

                return self._diff(
                    path,
                    old_content,
                    new_content,
                )

            return (
                f"CREATE FILE: {path}\n\n"
                + self._limit_preview(
                    new_content
                )
            )

        if operation == "edit_file":
            path = arguments["path"]

            old_content = (
                self.file_manager
                .read_file(path)["content"]
            )

            old_text = arguments["old_text"]
            new_text = arguments["new_text"]

            occurrences = old_content.count(
                old_text
            )

            if occurrences == 0:
                raise ValueError(
                    "The requested text was not found."
                )

            if occurrences > 1:
                raise ValueError(
                    "The requested text occurs multiple times."
                )

            updated_content = (
                old_content.replace(
                    old_text,
                    new_text,
                    1,
                )
            )

            return self._diff(
                path,
                old_content,
                updated_content,
            )

        if operation == "rename_file":
            source = arguments["source"]
            destination = arguments[
                "destination"
            ]

            self.file_manager.file_info(
                source
            )

            if self.file_manager.exists(
                destination
            ):
                raise FileExistsError(
                    "The destination already exists."
                )

            return (
                f"RENAME FILE\n"
                f"From: {source}\n"
                f"To:   {destination}"
            )

        if operation == "delete_file":
            path = arguments["path"]

            information = (
                self.file_manager
                .file_info(path)
            )

            return (
                "MOVE FILE TO WINDOWS RECYCLE BIN\n"
                f"Path: {information['path']}\n"
                f"Size: {information['size']} bytes"
            )

        raise ValueError(
            f"Unsupported operation: {operation}"
        )

    def approve_and_execute(
        self,
        approval_id: str,
    ) -> dict[str, Any]:
        self.approvals.approve(
            approval_id
        )

        approval = (
            self.approvals
            .claim_execution(
                approval_id
            )
        )

        try:
            result = self._execute_mutation(
                operation=approval["action"],
                arguments=approval["payload"],
            )

            self.approvals.finish_execution(
                approval_id
            )

            return {
                "status": "executed",
                "approval_id": approval_id,
                "operation": approval["action"],
                "result": result,
            }

        except Exception as error:
            self.approvals.finish_execution(
                approval_id,
                error=(
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
            )

            raise

    def reject(
        self,
        approval_id: str,
    ) -> dict[str, Any]:
        approval = self.approvals.reject(
            approval_id
        )

        return {
            "status": "rejected",
            "approval": approval,
        }

    def get_pending_approvals(
        self,
    ) -> list[dict[str, Any]]:
        return self.approvals.list_pending()

    def _execute_mutation(
        self,
        operation: str,
        arguments: dict[str, Any],
    ) -> Any:
        if operation == "write_file":
            return (
                self.file_manager
                .write_file(
                    relative_path=arguments[
                        "path"
                    ],
                    content=arguments[
                        "content"
                    ],
                    overwrite=arguments.get(
                        "overwrite",
                        False,
                    ),
                )
            )

        if operation == "edit_file":
            return (
                self.file_manager
                .edit_file(
                    relative_path=arguments[
                        "path"
                    ],
                    old_text=arguments[
                        "old_text"
                    ],
                    new_text=arguments[
                        "new_text"
                    ],
                )
            )

        if operation == "rename_file":
            return (
                self.file_manager
                .rename_file(
                    source_path=arguments[
                        "source"
                    ],
                    destination_path=arguments[
                        "destination"
                    ],
                )
            )

        if operation == "delete_file":
            return (
                self.file_manager
                .delete_file(
                    relative_path=arguments[
                        "path"
                    ]
                )
            )

        raise ValueError(
            f"Unsupported mutation: {operation}"
        )

    def _diff(
        self,
        path: str,
        old_content: str,
        new_content: str,
    ) -> str:
        diff = difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after)",
            lineterm="",
        )

        return self._limit_preview(
            "\n".join(diff)
        )

    @staticmethod
    def _limit_preview(
        text: str,
        maximum_characters: int = 12000,
    ) -> str:
        if len(text) <= maximum_characters:
            return text

        return (
            text[:maximum_characters]
            + "\n\n[Preview truncated]"
        )