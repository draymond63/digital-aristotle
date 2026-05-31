class AuditStore:
    """Persist update audit logs."""

    def write_audit_log(
        self,
        user_id: str,
        session_id: str | None,
        profile_backup_path: str | None,
        conversation_path: str | None,
        summary: str,
        changes: dict,
    ):
        """Write one update audit log entry."""
        audit_id = self._new_id("audit")
        self.cursor.execute(
            f"""
            INSERT INTO update_audit_log
                (id, user_id, session_id, profile_backup_path, conversation_path, summary, changes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, {self._now_sql()})
            """,
            (
                audit_id,
                user_id,
                session_id,
                profile_backup_path,
                conversation_path,
                summary,
                self._json(changes),
            ),
        )
        self.conn.commit()
        return audit_id
