import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from send2trash import send2trash


class FileManager:
    def __init__(
        self,
        workspace_root: str,
        allowed_extensions: set[str],
        max_file_size_bytes: int,
        database_path: str,
    ):
        self.workspace_root = Path(
            workspace_root
        ).resolve()

        self.allowed_extensions = {
            extension.lower()
            for extension in allowed_extensions
        }

        self.max_file_size_bytes = (
            max_file_size_bytes
        )

        self.database_path = database_path

        self.workspace_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.backup_root = (
            self.workspace_root
            / ".samsu_backups"
        )

        self.backup_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._create_audit_table()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row
        return connection

    def _create_audit_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS file_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _audit(
        self,
        operation: str,
        relative_path: str,
        details: str = "",
    ) -> None:
        created_at = datetime.now(
            timezone.utc
        ).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO file_audit_log (
                    operation,
                    relative_path,
                    details,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    operation,
                    relative_path,
                    details,
                    created_at,
                ),
            )

    def _resolve(
        self,
        relative_path: str,
    ) -> Path:
        if not relative_path:
            return self.workspace_root

        supplied_path = Path(relative_path)

        if supplied_path.is_absolute():
            raise ValueError(
                "Absolute paths are not allowed."
            )

        target = (
            self.workspace_root
            / supplied_path
        ).resolve(strict=False)

        try:
            target.relative_to(
                self.workspace_root
            )

        except ValueError as error:
            raise ValueError(
                "The path is outside the permitted workspace."
            ) from error

        return target

    def _relative(
        self,
        path: Path,
    ) -> str:
        return path.relative_to(
            self.workspace_root
        ).as_posix()

    def _validate_extension(
        self,
        path: Path,
    ) -> None:
        extension = path.suffix.lower()

        if extension not in self.allowed_extensions:
            raise ValueError(
                f"The '{extension}' file type is not allowed."
            )

    def _validate_content(
        self,
        content: str,
    ) -> bytes:
        encoded = content.encode("utf-8")

        if len(encoded) > self.max_file_size_bytes:
            raise ValueError(
                "The file content exceeds the maximum allowed size."
            )

        return encoded

    def _require_file(
        self,
        path: Path,
    ) -> None:
        if not path.exists():
            raise FileNotFoundError(
                f"File not found: {self._relative(path)}"
            )

        if not path.is_file():
            raise ValueError(
                "The requested path is not a file."
            )

        if path.is_symlink():
            raise ValueError(
                "Symbolic links are not allowed."
            )

    def _create_backup(
        self,
        path: Path,
    ) -> str | None:
        if not path.exists():
            return None

        relative = path.relative_to(
            self.workspace_root
        )

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%d-%H%M%S-%f")

        backup_directory = (
            self.backup_root
            / relative.parent
        )

        backup_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_path = backup_directory / (
            f"{relative.stem}-{timestamp}"
            f"{relative.suffix}.bak"
        )

        shutil.copy2(
            path,
            backup_path,
        )

        return self._relative(backup_path)

    def exists(
        self,
        relative_path: str,
    ) -> bool:
        path = self._resolve(relative_path)
        return path.exists()

    def list_directory(
        self,
        relative_path: str = "",
    ) -> list[dict[str, Any]]:
        directory = self._resolve(
            relative_path
        )

        if not directory.exists():
            raise FileNotFoundError(
                "Directory not found."
            )

        if not directory.is_dir():
            raise ValueError(
                "The requested path is not a directory."
            )

        if directory.is_symlink():
            raise ValueError(
                "Symbolic links are not allowed."
            )

        results = []

        for item in sorted(
            directory.iterdir(),
            key=lambda entry: (
                not entry.is_dir(),
                entry.name.lower(),
            ),
        ):
            if item == self.backup_root:
                continue

            if item.is_symlink():
                continue

            resolved = item.resolve()

            try:
                resolved.relative_to(
                    self.workspace_root
                )

            except ValueError:
                continue

            is_directory = item.is_dir()

            results.append(
                {
                    "name": item.name,
                    "path": self._relative(item),
                    "type": (
                        "directory"
                        if is_directory
                        else "file"
                    ),
                    "size": (
                        item.stat().st_size
                        if item.is_file()
                        else None
                    ),
                    "supported": (
                        is_directory
                        or item.suffix.lower()
                        in self.allowed_extensions
                    ),
                    "modified_at": (
                        datetime.fromtimestamp(
                            item.stat().st_mtime,
                            timezone.utc,
                        ).isoformat()
                    ),
                }
            )

        self._audit(
            operation="list_directory",
            relative_path=(
                relative_path or "."
            ),
        )

        return results

    def read_file(
        self,
        relative_path: str,
    ) -> dict[str, Any]:
        path = self._resolve(
            relative_path
        )

        self._require_file(path)
        self._validate_extension(path)

        size = path.stat().st_size

        if size > self.max_file_size_bytes:
            raise ValueError(
                "The file exceeds the maximum allowed size."
            )

        try:
            content = path.read_text(
                encoding="utf-8"
            )

        except UnicodeDecodeError as error:
            raise ValueError(
                "The file is not valid UTF-8 text."
            ) from error

        self._audit(
            operation="read_file",
            relative_path=self._relative(path),
        )

        return {
            "name": path.name,
            "path": self._relative(path),
            "size": size,
            "content": content,
        }

    def file_info(
        self,
        relative_path: str,
    ) -> dict[str, Any]:
        path = self._resolve(
            relative_path
        )

        self._require_file(path)

        return {
            "name": path.name,
            "path": self._relative(path),
            "size": path.stat().st_size,
            "extension": path.suffix.lower(),
            "modified_at": datetime.fromtimestamp(
                path.stat().st_mtime,
                timezone.utc,
            ).isoformat(),
        }

    def write_file(
        self,
        relative_path: str,
        content: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        path = self._resolve(
            relative_path
        )

        if path == self.workspace_root:
            raise ValueError(
                "A filename is required."
            )

        self._validate_extension(path)

        encoded = self._validate_content(
            content
        )

        if path.exists() and not overwrite:
            raise FileExistsError(
                "The file already exists."
            )

        if path.exists():
            self._require_file(path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_path = self._create_backup(
            path
        )

        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=path.parent,
                prefix=".samsu-",
                suffix=".tmp",
            ) as temporary_file:
                temporary_file.write(encoded)

                temporary_file.flush()
                os.fsync(
                    temporary_file.fileno()
                )

                temporary_path = Path(
                    temporary_file.name
                )

            os.replace(
                temporary_path,
                path,
            )

        except Exception:
            if (
                temporary_path
                and temporary_path.exists()
            ):
                temporary_path.unlink(
                    missing_ok=True
                )

            raise

        relative = self._relative(path)

        self._audit(
            operation="write_file",
            relative_path=relative,
            details=(
                f"size={len(encoded)}, "
                f"backup={backup_path}"
            ),
        )

        return {
            "status": "written",
            "path": relative,
            "size": len(encoded),
            "backup_path": backup_path,
        }

    def edit_file(
        self,
        relative_path: str,
        old_text: str,
        new_text: str,
    ) -> dict[str, Any]:
        if not old_text:
            raise ValueError(
                "old_text cannot be empty."
            )

        file_data = self.read_file(
            relative_path
        )

        current_content = file_data[
            "content"
        ]

        occurrences = current_content.count(
            old_text
        )

        if occurrences == 0:
            raise ValueError(
                "The requested text was not found."
            )

        if occurrences > 1:
            raise ValueError(
                "The requested text occurs multiple times. "
                "Provide a more specific selection."
            )

        updated_content = (
            current_content.replace(
                old_text,
                new_text,
                1,
            )
        )

        result = self.write_file(
            relative_path=relative_path,
            content=updated_content,
            overwrite=True,
        )

        result["status"] = "edited"

        self._audit(
            operation="edit_file",
            relative_path=relative_path,
        )

        return result

    def rename_file(
        self,
        source_path: str,
        destination_path: str,
    ) -> dict[str, Any]:
        source = self._resolve(
            source_path
        )

        destination = self._resolve(
            destination_path
        )

        self._require_file(source)
        self._validate_extension(source)
        self._validate_extension(destination)

        if destination.exists():
            raise FileExistsError(
                "The destination already exists."
            )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        source.rename(destination)

        self._audit(
            operation="rename_file",
            relative_path=self._relative(source),
            details=(
                "destination="
                f"{self._relative(destination)}"
            ),
        )

        return {
            "status": "renamed",
            "source": source_path,
            "destination": (
                self._relative(destination)
            ),
        }

    def delete_file(
        self,
        relative_path: str,
    ) -> dict[str, Any]:
        path = self._resolve(
            relative_path
        )

        self._require_file(path)

        relative = self._relative(path)

        send2trash(str(path))

        self._audit(
            operation="delete_to_recycle_bin",
            relative_path=relative,
        )

        return {
            "status": "moved_to_recycle_bin",
            "path": relative,
        }

    def search_files(
        self,
        query: str,
        search_content: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = query.strip().lower()

        if not query:
            raise ValueError(
                "A search query is required."
            )

        limit = max(
            1,
            min(limit, 100),
        )

        results = []

        for path in self.workspace_root.rglob(
            "*"
        ):
            if len(results) >= limit:
                break

            if (
                not path.is_file()
                or path.is_symlink()
            ):
                continue

            if self.backup_root in path.parents:
                continue

            try:
                path.resolve().relative_to(
                    self.workspace_root
                )

            except ValueError:
                continue

            relative = self._relative(path)

            if query in path.name.lower():
                results.append(
                    {
                        "path": relative,
                        "match_type": "filename",
                    }
                )

                continue

            if (
                not search_content
                or path.suffix.lower()
                not in self.allowed_extensions
                or path.stat().st_size
                > self.max_file_size_bytes
            ):
                continue

            try:
                content = path.read_text(
                    encoding="utf-8"
                )

            except (
                UnicodeDecodeError,
                OSError,
            ):
                continue

            position = content.lower().find(
                query
            )

            if position >= 0:
                start = max(
                    0,
                    position - 80,
                )

                end = min(
                    len(content),
                    position + len(query) + 80,
                )

                results.append(
                    {
                        "path": relative,
                        "match_type": "content",
                        "preview": content[
                            start:end
                        ],
                    }
                )

        self._audit(
            operation="search_files",
            relative_path=".",
            details=f"query={query}",
        )

        return results