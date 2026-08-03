import re
import sqlite3
from datetime import datetime, timezone


class MemoryStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._create_table()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 5,
                    created_at TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_user
                ON memories (user_id, importance, id)
                """
            )

    def add_memory(
        self,
        user_id: str,
        content: str,
        importance: int = 5,
    ) -> int:
        importance = max(1, min(10, importance))
        created_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memories (
                    user_id,
                    content,
                    importance,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    content.strip(),
                    importance,
                    created_at,
                ),
            )

            return int(cursor.lastrowid)

    def search_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 8,
    ) -> list[dict]:
        words = self._extract_keywords(query)

        with self._connect() as connection:
            if not words:
                rows = connection.execute(
                    """
                    SELECT id, content, importance, created_at
                    FROM memories
                    WHERE user_id = ?
                    ORDER BY importance DESC, id DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            else:
                conditions = " OR ".join(
                    ["LOWER(content) LIKE ?" for _ in words]
                )

                parameters = [user_id]
                parameters.extend(f"%{word}%" for word in words)
                parameters.append(limit)

                rows = connection.execute(
                    f"""
                    SELECT id, content, importance, created_at
                    FROM memories
                    WHERE user_id = ?
                      AND ({conditions})
                    ORDER BY importance DESC, id DESC
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()

        return [dict(row) for row in rows]

    def list_memories(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, content, importance, created_at
                FROM memories
                WHERE user_id = ?
                ORDER BY importance DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        return [dict(row) for row in rows]

    def delete_memory(
        self,
        user_id: str,
        memory_id: int,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memories
                WHERE user_id = ?
                  AND id = ?
                """,
                (
                    user_id,
                    memory_id,
                ),
            )

            return cursor.rowcount > 0

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        ignored_words = {
            "the",
            "and",
            "that",
            "this",
            "with",
            "from",
            "have",
            "what",
            "when",
            "where",
            "which",
            "would",
            "could",
            "should",
            "about",
            "your",
            "please",
            "continue",
        }

        words = re.findall(r"[a-zA-Z0-9_+#.-]{3,}", text.lower())

        unique_words = []

        for word in words:
            if word in ignored_words:
                continue

            if word not in unique_words:
                unique_words.append(word)

        return unique_words[:8]