import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from send2trash import send2trash

from files.adapter_registry import AdapterRegistry


class WorkspaceManager:
    """Secure, versioned, atomic file access beneath one workspace root."""

    def __init__(
        self,
        workspace_root: str | Path,
        database_path: str | Path,
        max_file_bytes: int = 25 * 1024 * 1024,
    ):
        self.root = Path(workspace_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = str(database_path)
        self.max_file_bytes = max_file_bytes
        self.registry = AdapterRegistry(max_text_bytes=min(max_file_bytes, 5 * 1024 * 1024))
        self.versions_root = self.root / ".samsu" / "versions"
        self.versions_root.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _create_tables(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace_file_versions (
                    id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workspace_versions_path
                ON workspace_file_versions(relative_path, created_at DESC);

                CREATE TABLE IF NOT EXISTS workspace_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    details_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def resolve(self, relative_path: str, allow_root: bool = False) -> Path:
        if not isinstance(relative_path, str):
            raise TypeError("Workspace path must be a string.")
        supplied = Path(relative_path.replace("\\", "/"))
        if supplied.is_absolute():
            raise ValueError("Absolute paths are not allowed.")
        target = (self.root / supplied).resolve(strict=False)
        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError("Path escapes the permitted workspace.") from error
        if target == self.root and not allow_root:
            raise ValueError("A file or directory path is required.")
        self._reject_symlink_chain(target)
        return target

    def _reject_symlink_chain(self, target: Path) -> None:
        current = self.root
        for part in target.relative_to(self.root).parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("Symbolic links are not allowed in the workspace.")

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def list_directory(self, relative_path: str = "") -> list[dict[str, Any]]:
        directory = self.resolve(relative_path, allow_root=True)
        if not directory.is_dir():
            raise NotADirectoryError(relative_path)
        items = []
        for path in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if path.name == ".samsu" or path.is_symlink():
                continue
            items.append(
                {
                    "name": path.name,
                    "path": self.relative(path),
                    "type": "directory" if path.is_dir() else "file",
                    "size": path.stat().st_size if path.is_file() else None,
                }
            )
        return items

    def read_file(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        if path.stat().st_size > self.max_file_bytes:
            raise ValueError("File exceeds the configured size limit.")
        result = self.registry.get(path).read(path)
        result.update(path=self.relative(path), size=path.stat().st_size)
        self._audit("read", path, {})
        return result

    def write_file(
        self,
        relative_path: str,
        payload: Any,
        overwrite: bool = False,
        operation: str = "create",
    ) -> dict[str, Any]:
        path = self.resolve(relative_path)
        if path.exists() and not overwrite:
            raise FileExistsError(relative_path)
        if path.exists() and not path.is_file():
            raise ValueError("Target exists and is not a regular file.")
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = self._backup(path, operation) if path.exists() else None
        adapter = self.registry.get(path)
        temporary = self._temporary_path(path)
        try:
            details = adapter.create(temporary, payload)
            if temporary.stat().st_size > self.max_file_bytes:
                raise ValueError("Generated file exceeds the configured size limit.")
            verification = adapter.verify(temporary)
            self._flush_file(temporary)
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        result = {
            "status": "written",
            "path": self.relative(path),
            "absolute_path": str(path),
            "size": path.stat().st_size,
            "backup_path": backup,
            "details": details,
            "verification": verification,
        }
        self._audit("write", path, result)
        return result

    def edit_file(
        self,
        relative_path: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        if not operations:
            raise ValueError("At least one edit operation is required.")
        adapter = self.registry.get(path)
        if not self.registry.is_semantically_editable(path):
            raise ValueError("This file type supports copy/rename/download only.")
        backup = self._backup(path, "edit")
        temporary = self._temporary_path(path)
        try:
            shutil.copy2(path, temporary)
            details = adapter.edit(temporary, operations)
            if temporary.stat().st_size > self.max_file_bytes:
                raise ValueError("Edited file exceeds the configured size limit.")
            verification = adapter.verify(temporary)
            self._flush_file(temporary)
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        result = {
            "status": "edited",
            "path": self.relative(path),
            "absolute_path": str(path),
            "size": path.stat().st_size,
            "backup_path": backup,
            "details": details,
            "verification": verification,
        }
        self._audit("edit", path, result)
        return result

    def verify_file(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path)
        result = self.registry.get(path).verify(path)
        result.update(path=self.relative(path), size=path.stat().st_size)
        return result

    def create_directory(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path)
        path.mkdir(parents=True, exist_ok=True)
        result = {"status": "created", "path": self.relative(path), "type": "directory"}
        self._audit("mkdir", path, result)
        return result

    def rename_path(self, source_path: str, destination_path: str) -> dict[str, Any]:
        source = self.resolve(source_path)
        destination = self.resolve(destination_path)
        if not source.exists():
            raise FileNotFoundError(source_path)
        if destination.exists():
            raise FileExistsError(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        result = {
            "status": "renamed",
            "source": source_path.replace("\\", "/"),
            "path": self.relative(destination),
        }
        self._audit("rename", destination, result)
        return result

    def delete_file(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        backup = self._backup(path, "delete")
        original = self.relative(path)
        send2trash(str(path))
        result = {
            "status": "moved_to_recycle_bin",
            "path": original,
            "backup_path": backup,
            "recoverable": True,
        }
        self._audit_relative("delete", original, result)
        return result

    def restore_version(self, version_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspace_file_versions WHERE id = ?", (version_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Version not found.")
        path = self.resolve(row["relative_path"])
        backup = self.resolve(row["backup_path"])
        if not backup.is_file():
            raise FileNotFoundError("Stored backup is missing.")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, path)
        result = self.verify_file(row["relative_path"])
        self._audit("restore", path, {"version_id": version_id})
        return result

    def _temporary_path(self, path: Path) -> Path:
        handle = tempfile.NamedTemporaryFile(
            delete=False,
            dir=path.parent,
            prefix=".samsu-",
            suffix=path.suffix,
        )
        handle.close()
        temporary = Path(handle.name)
        temporary.unlink(missing_ok=True)
        return temporary

    @staticmethod
    def _flush_file(path: Path) -> None:
        with path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())

    def _backup(self, path: Path, operation: str) -> str:
        version_id = uuid4().hex
        relative = self.relative(path)
        destination = self.versions_root / version_id / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        backup_relative = self.relative(destination)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_file_versions
                (id, relative_path, backup_path, operation, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (version_id, relative, backup_relative, operation, self._now()),
            )
        return backup_relative

    def _audit(self, operation: str, path: Path, details: dict[str, Any]) -> None:
        self._audit_relative(operation, self.relative(path), details)

    def _audit_relative(
        self,
        operation: str,
        relative_path: str,
        details: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_audit
                (operation, relative_path, details_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    operation,
                    relative_path,
                    json.dumps(details, ensure_ascii=False, default=str),
                    self._now(),
                ),
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
