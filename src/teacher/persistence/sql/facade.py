import json
import uuid
from pathlib import Path

from teacher.persistence.sql.audits import AuditStore
from teacher.persistence.sql.learning_sessions import LearningSessionStore
from teacher.persistence.sql.schema import init_db
from teacher.persistence.sql.semantic_memories import SemanticMemoryRows
from teacher.persistence.sql.topic_graph import TopicGraphStore


class SQLDatabase(TopicGraphStore, LearningSessionStore, SemanticMemoryRows, AuditStore):
    """Own a SQLite connection and expose persistence repositories."""

    def __init__(self, path="data/aristotle.db"):
        """Open a SQLite database and initialize its schema."""
        path = Path(path)
        self.conn = init_db(path)
        self.cursor = self.conn.cursor()

    def close(self):
        """Close the SQLite connection."""
        self.conn.close()

    @staticmethod
    def _now_sql():
        """Return the SQLite expression for the current timestamp."""
        return "datetime('now')"

    @staticmethod
    def _new_id(prefix: str):
        """Create a short prefixed random identifier."""
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _json(data) -> str:
        """Serialize data to compact JSON text."""
        return json.dumps({} if data is None else data, ensure_ascii=True)

    @staticmethod
    def _loads(value: str | None):
        """Deserialize JSON text into a dictionary."""
        return json.loads(value) if value else {}

    @staticmethod
    def row_to_dict(row):
        """Convert a SQLite row into a dictionary."""
        if row is None:
            return None
        return dict(row)
