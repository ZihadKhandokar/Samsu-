import sqlite3
from datetime import datetime, timezone


class UserProfileStore:
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
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    name TEXT,
                    preferred_language TEXT,
                    custom_instructions TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get_profile(self, user_id: str) -> dict[str, str | None]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    name,
                    preferred_language,
                    custom_instructions
                FROM user_profiles
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        if row is None:
            return {
                "name": None,
                "preferred_language": None,
                "custom_instructions": None,
            }

        return {
            "name": row["name"],
            "preferred_language": row["preferred_language"],
            "custom_instructions": row["custom_instructions"],
        }

    def update_profile(
        self,
        user_id: str,
        name: str | None = None,
        preferred_language: str | None = None,
        custom_instructions: str | None = None,
    ) -> None:
        current = self.get_profile(user_id)

        final_name = (
            name if name is not None else current["name"]
        )

        final_language = (
            preferred_language
            if preferred_language is not None
            else current["preferred_language"]
        )

        final_instructions = (
            custom_instructions
            if custom_instructions is not None
            else current["custom_instructions"]
        )

        updated_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_profiles (
                    user_id,
                    name,
                    preferred_language,
                    custom_instructions,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = excluded.name,
                    preferred_language = excluded.preferred_language,
                    custom_instructions = excluded.custom_instructions,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    final_name,
                    final_language,
                    final_instructions,
                    updated_at,
                ),
            )