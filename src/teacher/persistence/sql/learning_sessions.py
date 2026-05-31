class LearningSessionStore:
    """Persist learning sessions and mastery history."""

    def add_user(self, user_id: str):
        """Insert a user row."""
        self.cursor.execute("INSERT INTO users (id, created_at) VALUES (?, datetime('now'))", (user_id,))
        self.conn.commit()

    def abandon_active_question_sessions(self, user_id: str):
        """Mark active question sessions as abandoned for a user."""
        self.cursor.execute(
            """
            UPDATE learning_sessions
            SET status = 'abandoned', ended_at = datetime('now')
            WHERE user_id = ? AND session_type = 'question' AND status = 'active'
            """,
            (user_id,),
        )
        self.conn.commit()

    def create_learning_session(self, user_id: str, session_type: str, metadata: dict | None = None):
        """Create an active learning session."""
        session_id = self._new_id("sess")
        self.cursor.execute(
            f"""
            INSERT INTO learning_sessions
                (id, user_id, session_type, status, started_at, metadata_json)
            VALUES (?, ?, ?, 'active', {self._now_sql()}, ?)
            """,
            (session_id, user_id, session_type, self._json(metadata)),
        )
        self.conn.commit()
        return session_id

    def finish_learning_session(
        self,
        session_id: str,
        conversation_path: str | None = None,
        summary: str | None = None,
        next_step: str | None = None,
        status: str = "done",
    ):
        """Finish or close a learning session."""
        self.cursor.execute(
            f"""
            UPDATE learning_sessions
            SET status = ?, ended_at = {self._now_sql()}, conversation_path = ?,
                summary = ?, next_step = ?
            WHERE id = ?
            """,
            (status, conversation_path, summary, next_step, session_id),
        )
        self.conn.commit()

    def save_learning_session_progress(self, session_id: str, conversation_path: str):
        """Save conversation progress for an active learning session."""
        self.cursor.execute(
            """
            UPDATE learning_sessions
            SET conversation_path = ?
            WHERE id = ? AND status = 'active'
            """,
            (conversation_path, session_id),
        )
        self.conn.commit()

    def find_active_learning_session(self, user_id: str, session_type: str = "question") -> dict | None:
        """Find the newest active learning session for a user."""
        self.cursor.execute(
            """
            SELECT id, user_id, session_type, status, conversation_path, metadata_json
            FROM learning_sessions
            WHERE user_id = ? AND session_type = ? AND status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id, session_type),
        )
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def find_learning_session_by_conversation(self, user_id: str, conversation_path: str) -> str | None:
        """Find the learning session associated with a conversation path."""
        self.cursor.execute(
            """
            SELECT id
            FROM learning_sessions
            WHERE user_id = ? AND conversation_path = ?
            ORDER BY ended_at DESC, started_at DESC
            LIMIT 1
            """,
            (user_id, conversation_path),
        )
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def record_mastery(
        self,
        user_id: str,
        topic_id: str,
        mastery: float,
        intuition: float | None,
        details: float | None,
        confidence: float | None,
        evidence: str,
    ):
        """Record one mastery history row."""
        self.cursor.execute(
            """
            INSERT INTO mastery_history
                (user_id, topic_id, mastery, timestamp, intuition, details, confidence, evidence)
            VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?)
            """,
            (user_id, topic_id, mastery, intuition, details, confidence, evidence),
        )
        self.conn.commit()
