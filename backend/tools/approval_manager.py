import json
import sqlite3
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from typing import Any
from uuid import uuid4


class ApprovalManager:
    def __init__(
        self,
        database_path: str,
        expiration_minutes: int = 10,
    ):
        self.database_path = database_path

        self.expiration_minutes = (
            expiration_minutes
        )

        self._create_table()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row
        return connection

    def _create_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS file_approvals (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    decided_at TEXT,
                    executed_at TEXT
                )
                """
            )

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _decode(
        self,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = dict(row)

        result["payload"] = json.loads(
            result.pop("payload_json")
        )

        return result

    def create(
        self,
        action: str,
        payload: dict[str, Any],
        preview: str,
    ) -> dict[str, Any]:
        approval_id = uuid4().hex

        created_at = self._now()

        expires_at = (
            created_at
            + timedelta(
                minutes=self.expiration_minutes
            )
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO file_approvals (
                    id,
                    action,
                    payload_json,
                    preview,
                    status,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    action,
                    json.dumps(payload),
                    preview,
                    "pending",
                    created_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )

        return self.get(approval_id)

    def get(
        self,
        approval_id: str,
    ) -> dict[str, Any]:
        self.expire_old()

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM file_approvals
                WHERE id = ?
                """,
                (approval_id,),
            ).fetchone()

        if row is None:
            raise KeyError(
                "Approval request not found."
            )

        return self._decode(row)

    def list_pending(
        self,
    ) -> list[dict[str, Any]]:
        self.expire_old()

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM file_approvals
                WHERE status = 'pending'
                ORDER BY created_at DESC
                """
            ).fetchall()

        return [
            self._decode(row)
            for row in rows
        ]

    def approve(
        self,
        approval_id: str,
    ) -> dict[str, Any]:
        decided_at = self._now().isoformat()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE file_approvals
                SET
                    status = 'approved',
                    decided_at = ?
                WHERE id = ?
                  AND status = 'pending'
                  AND expires_at > ?
                """,
                (
                    decided_at,
                    approval_id,
                    decided_at,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "The approval is missing, expired, "
                    "or already decided."
                )

        return self.get(approval_id)

    def reject(
        self,
        approval_id: str,
    ) -> dict[str, Any]:
        decided_at = self._now().isoformat()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE file_approvals
                SET
                    status = 'rejected',
                    decided_at = ?
                WHERE id = ?
                  AND status = 'pending'
                """,
                (
                    decided_at,
                    approval_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "The approval is missing or "
                    "already decided."
                )

        return self.get(approval_id)

    def claim_execution(
        self,
        approval_id: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE file_approvals
                SET status = 'executing'
                WHERE id = ?
                  AND status = 'approved'
                """,
                (approval_id,),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "The operation is not approved "
                    "or has already been executed."
                )

        return self.get(approval_id)

    def finish_execution(
        self,
        approval_id: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        status = (
            "failed"
            if error
            else "executed"
        )

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE file_approvals
                SET
                    status = ?,
                    error = ?,
                    executed_at = ?
                WHERE id = ?
                  AND status = 'executing'
                """,
                (
                    status,
                    error,
                    self._now().isoformat(),
                    approval_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "The operation is not being executed."
                )

        return self.get(approval_id)

    def expire_old(self) -> None:
        now = self._now().isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE file_approvals
                SET status = 'expired'
                WHERE status = 'pending'
                  AND expires_at <= ?
                """,
                (now,),
            )