import sqlite3
from datetime import datetime, timezone


class ChatHistory:
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
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_lookup
                ON chat_messages (user_id, conversation_id, id)
                """
            )

    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_messages (
                    user_id, conversation_id, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, conversation_id, role, content, created_at),
            )

    def get_recent_messages(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 30,
    ) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, conversation_id, limit),
            ).fetchall()

        return [
            {"role": row["role"], "content": row["content"]}
            for row in reversed(rows)
        ]

    def get_conversation_messages(
        self,
        user_id: str,
        conversation_id: str,
    ) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at
                FROM chat_messages
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY id ASC
                """,
                (user_id, conversation_id),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_conversations(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    messages.conversation_id,
                    COALESCE(
                        (
                            SELECT first_message.content
                            FROM chat_messages AS first_message
                            WHERE first_message.user_id = messages.user_id
                              AND first_message.conversation_id = messages.conversation_id
                              AND first_message.role = 'user'
                            ORDER BY first_message.id ASC
                            LIMIT 1
                        ),
                        'New conversation'
                    ) AS title,
                    MAX(messages.created_at) AS updated_at,
                    COUNT(*) AS message_count,
                    MAX(messages.id) AS last_message_id
                FROM chat_messages AS messages
                WHERE messages.user_id = ?
                GROUP BY messages.user_id, messages.conversation_id
                ORDER BY last_message_id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        conversations = []
        for row in rows:
            item = dict(row)
            item.pop("last_message_id", None)
            title = " ".join(item["title"].split())
            item["title"] = title[:54] + ("..." if len(title) > 54 else "")
            conversations.append(item)
        return conversations

    def clear_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM chat_messages
                WHERE user_id = ? AND conversation_id = ?
                """,
                (user_id, conversation_id),
            )
            return cursor.rowcount > 0
