class SemanticMemoryRows:
    """Persist semantic memory SQL rows."""

    def insert_semantic_memory(
        self,
        user_id: str,
        session_id: str,
        collection: str,
        topic_id: str,
        text: str,
        extraction_prompt_version: str,
        memory_id: str | None = None,
    ) -> str:
        """Insert one semantic memory row."""
        memory_id = memory_id or self._new_id("mem")
        self.cursor.execute(
            f"""
            INSERT INTO semantic_memories
                (id, user_id, session_id, collection, topic_id, text, extraction_prompt_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, {self._now_sql()})
            """,
            (memory_id, user_id, session_id, collection, topic_id, text, extraction_prompt_version),
        )
        self.conn.commit()
        return memory_id

    def delete_semantic_memory(self, memory_id: str):
        """Delete one semantic memory SQL row."""
        self.cursor.execute("DELETE FROM semantic_memories WHERE id = ?", (memory_id,))
        self.conn.commit()

    def live_semantic_memory_ids(self, user_id: str, session_id: str, collection: str | None = None) -> list[str]:
        """Return live semantic memory IDs for a session."""
        if collection:
            self.cursor.execute(
                """
                SELECT id
                FROM semantic_memories
                WHERE user_id = ? AND session_id = ? AND collection = ? AND replaced_at IS NULL
                ORDER BY created_at, id
                """,
                (user_id, session_id, collection),
            )
        else:
            self.cursor.execute(
                """
                SELECT id
                FROM semantic_memories
                WHERE user_id = ? AND session_id = ? AND replaced_at IS NULL
                ORDER BY created_at, id
                """,
                (user_id, session_id),
            )
        return [row["id"] for row in self.cursor.fetchall()]

    def mark_semantic_memories_replaced(self, user_id: str, session_id: str) -> int:
        """Mark a session's live semantic memories as replaced."""
        self.cursor.execute(
            f"""
            UPDATE semantic_memories
            SET replaced_at = {self._now_sql()}
            WHERE user_id = ? AND session_id = ? AND replaced_at IS NULL
            """,
            (user_id, session_id),
        )
        count = self.cursor.rowcount
        self.conn.commit()
        return count
