import sqlite3
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from brains.data.profile import normalize_identifier


@dataclass
class EventType:
    SESSION_START = "session_start"
    MASTERY_UPDATE = "mastery_update"


@dataclass
class RelationType:
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    PART_OF = "part_of"
    APPLICATION_OF = "application_of"
    ENABLES = "enables"


class SQLDatabase:
    def __init__(self, path="data/aristotle.db"):
        path = Path(path)
        self.conn = self.init_db(path)
        self.cursor = self.conn.cursor()

    def close(self):
        self.conn.close()

    @staticmethod
    def init_db(path: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # ---- USERS ----
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            created_at TEXT
        )
        """)

        # ---- TOPICS (graph nodes) ----
        c.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT
        )
        """)

        # ---- TOPIC RELATIONS (graph edges) ----
        c.execute("""
        CREATE TABLE IF NOT EXISTS topic_edges (
            topic1 TEXT,
            topic2 TEXT,
            relation_type TEXT, -- prerequisite | related | subtopic
            PRIMARY KEY (topic1, topic2, relation_type)
        )
        """)

        # ---- TOPIC CONTEXT (Topics related to what sessions) ----
        c.execute("""
        CREATE TABLE IF NOT EXISTS topic_context (
            topic_id TEXT,
            context_type TEXT, -- lesson | question | misconception | insight
            context_id TEXT,
            PRIMARY KEY (topic_id, context_type, context_id)
        )
        """)

        # ---- LESSONS (sessions) ----
        c.execute("""
        CREATE TABLE IF NOT EXISTS lessons (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            topic_id TEXT,
            started_at TEXT,
            ended_at TEXT
        )
        """)

        # ---- EVENTS (chronology of learning) ----
        c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            type TEXT, -- question | explanation | misconception | insight
            topic_id TEXT,
            content TEXT,
            timestamp TEXT
        )
        """)

        # ---- MASTERY HISTORY (time series) ----
        c.execute("""
        CREATE TABLE IF NOT EXISTS mastery_history (
            user_id TEXT,
            topic_id TEXT,
            mastery REAL,
            timestamp TEXT
        )
        """)

        SQLDatabase._add_column_if_missing(conn, "topics", "aliases_json", "TEXT")
        SQLDatabase._add_column_if_missing(conn, "topics", "created_from", "TEXT")
        SQLDatabase._add_column_if_missing(conn, "topics", "confidence", "REAL DEFAULT 0.5")
        SQLDatabase._add_column_if_missing(conn, "topic_edges", "confidence", "REAL DEFAULT 0.5")
        SQLDatabase._add_column_if_missing(conn, "topic_edges", "evidence", "TEXT")
        SQLDatabase._add_column_if_missing(conn, "topic_edges", "created_from_session_id", "TEXT")
        SQLDatabase._add_column_if_missing(conn, "events", "session_id", "TEXT")
        SQLDatabase._add_column_if_missing(conn, "events", "metadata_json", "TEXT")
        SQLDatabase._add_column_if_missing(conn, "mastery_history", "intuition", "REAL")
        SQLDatabase._add_column_if_missing(conn, "mastery_history", "details", "REAL")
        SQLDatabase._add_column_if_missing(conn, "mastery_history", "confidence", "REAL")
        SQLDatabase._add_column_if_missing(conn, "mastery_history", "evidence", "TEXT")

        c.execute("""
        CREATE TABLE IF NOT EXISTS learning_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            conversation_path TEXT,
            summary TEXT,
            next_step TEXT,
            metadata_json TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS update_audit_log (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT,
            profile_backup_path TEXT,
            conversation_path TEXT,
            summary TEXT,
            changes_json TEXT,
            created_at TEXT NOT NULL
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS semantic_memories (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            collection TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            text TEXT NOT NULL,
            extraction_prompt_version TEXT,
            created_at TEXT NOT NULL,
            replaced_at TEXT
        )
        """)

        conn.commit()
        return conn

    @staticmethod
    def _add_column_if_missing(conn, table: str, column: str, declaration: str):
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in c.fetchall()}
        if column not in columns:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def _now_sql():
        return "datetime('now')"

    @staticmethod
    def _new_id(prefix: str):
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _json(data) -> str:
        return json.dumps({} if data is None else data, ensure_ascii=True)

    @staticmethod
    def _loads(value: str | None):
        return json.loads(value) if value else {}

    @staticmethod
    def row_to_dict(row):
        if row is None:
            return None
        return dict(row)

    ### Addition

    def add_user(self, user_id: str):
        self.cursor.execute("INSERT INTO users (id, created_at) VALUES (?, datetime('now'))", (user_id,))
        self.conn.commit()

    def log_session_start(self, user_id: str, message: str):
        self.cursor.execute(
            "INSERT INTO events (user_id, type, content, timestamp) VALUES (?, ?, ?, datetime('now'))",
            (user_id, EventType.SESSION_START, message)
        )
        self.conn.commit()
        # Get and return the session ID
        return self.cursor.lastrowid

    def connect_topic_to_session(self, session_id: str, topics: list[str]):
        for topic in topics:
            topic_id = self.upsert_topic(topic, name=topic)
            # Relate topics to session
            self.cursor.execute(
                "INSERT OR IGNORE INTO topic_context (topic_id, context_type, context_id) VALUES (?, ?, ?)",
                (topic_id, EventType.SESSION_START, session_id)
            )
        self.conn.commit()

    @staticmethod
    def create_topic_id(topic: str):
        return normalize_identifier(topic)

    def _aliases_for_topic(self, topic_id: str) -> list[str]:
        self.cursor.execute("SELECT aliases_json FROM topics WHERE id = ?", (topic_id,))
        row = self.cursor.fetchone()
        if not row:
            return []
        try:
            aliases = json.loads(row["aliases_json"] or "[]")
        except json.JSONDecodeError:
            return []
        return aliases if isinstance(aliases, list) else []

    def resolve_topic_id(self, topic: str | None) -> str:
        topic_id = self.create_topic_id(topic or "")
        if not topic_id:
            return ""
        candidate_ids = [topic_id]
        if topic_id.endswith("ies"):
            candidate_ids.append(f"{topic_id[:-3]}y")
        if topic_id.endswith("s"):
            candidate_ids.append(topic_id[:-1])
        for candidate_id in candidate_ids:
            self.cursor.execute("SELECT id FROM topics WHERE id = ?", (candidate_id,))
            row = self.cursor.fetchone()
            if row:
                return row["id"]
        self.cursor.execute("SELECT id, aliases_json FROM topics")
        for row in self.cursor.fetchall():
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except json.JSONDecodeError:
                aliases = []
            normalized_aliases = {self.create_topic_id(alias) for alias in aliases if alias}
            if topic_id in normalized_aliases:
                return row["id"]
        return topic_id

    def topic_exists(self, topic_id: str) -> bool:
        topic_id = self.resolve_topic_id(topic_id)
        if not topic_id:
            return False
        self.cursor.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,))
        return self.cursor.fetchone() is not None

    def get_topic_summaries(self, limit: int = 50) -> list[dict]:
        self.cursor.execute(
            """
            SELECT id, name, description, aliases_json, confidence
            FROM topics
            ORDER BY confidence DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        )
        summaries = []
        for row in self.cursor.fetchall():
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except json.JSONDecodeError:
                aliases = []
            summaries.append(
                {
                    "topic_id": row["id"],
                    "name": row["name"],
                    "description": row["description"] or "",
                    "aliases": aliases if isinstance(aliases, list) else [],
                    "confidence": row["confidence"],
                }
            )
        return summaries

    def connected_targets(self, start_topics: list[str], target_topics: list[str], max_hops: int = 2) -> list[str]:
        starts = {self.resolve_topic_id(topic) for topic in start_topics if self.resolve_topic_id(topic)}
        targets = {self.resolve_topic_id(topic) for topic in target_topics if self.resolve_topic_id(topic)}
        if not starts or not targets:
            return []
        found = set(starts & targets)
        frontier = set(starts)
        visited = set(starts)
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            self.cursor.execute(
                f"""
                SELECT topic1, topic2 FROM topic_edges
                WHERE topic1 IN ({placeholders})
                OR topic2 IN ({placeholders})
                """,
                [*frontier, *frontier],
            )
            neighbors = set()
            for row in self.cursor.fetchall():
                neighbors.add(row["topic1"])
                neighbors.add(row["topic2"])
            neighbors -= visited
            found |= neighbors & targets
            visited |= neighbors
            frontier = neighbors
        return [topic for topic in target_topics if self.resolve_topic_id(topic) in found]

    def merge_topics(self, source_id: str, target_id: str) -> bool:
        source_raw = str(source_id or "")
        source_resolved = self.resolve_topic_id(source_raw)
        target_id = self.resolve_topic_id(target_id)
        self.cursor.execute("SELECT * FROM topics WHERE id = ?", (source_raw,))
        exact_source = self.cursor.fetchone()
        source_id = source_raw if exact_source and source_raw != target_id else source_resolved
        if not source_id or not target_id or source_id == target_id:
            return False
        self.cursor.execute("SELECT * FROM topics WHERE id = ?", (source_id,))
        source = self.cursor.fetchone()
        if not source:
            return False
        self.upsert_topic(
            target_id,
            aliases=[source_id, source["name"], *self._aliases_for_topic(source_id)],
            description=source["description"],
            confidence=float(source["confidence"] or 0.5),
        )
        for column in ("topic1", "topic2"):
            self.cursor.execute(f"SELECT * FROM topic_edges WHERE {column} = ?", (source_id,))
            for edge in self.cursor.fetchall():
                topic1 = target_id if edge["topic1"] == source_id else edge["topic1"]
                topic2 = target_id if edge["topic2"] == source_id else edge["topic2"]
                if topic1 != topic2:
                    self.upsert_topic_edge(
                        topic1,
                        topic2,
                        edge["relation_type"],
                        confidence=float(edge["confidence"] or 0.5),
                        evidence=edge["evidence"],
                        session_id=edge["created_from_session_id"],
                    )
        self.cursor.execute("UPDATE OR IGNORE topic_context SET topic_id = ? WHERE topic_id = ?", (target_id, source_id))
        self.cursor.execute("UPDATE OR IGNORE mastery_history SET topic_id = ? WHERE topic_id = ?", (target_id, source_id))
        self.cursor.execute("DELETE FROM topic_context WHERE topic_id = ?", (source_id,))
        self.cursor.execute("DELETE FROM mastery_history WHERE topic_id = ?", (source_id,))
        self.cursor.execute("DELETE FROM topic_edges WHERE topic1 = ? OR topic2 = ?", (source_id, source_id))
        self.cursor.execute("DELETE FROM topics WHERE id = ?", (source_id,))
        self.conn.commit()
        return True

    def upsert_topic(
        self,
        topic_id: str,
        name: str | None = None,
        description: str | None = None,
        aliases: list[str] | None = None,
        created_from: str | None = None,
        confidence: float = 0.5,
    ):
        original_id = self.create_topic_id(topic_id)
        if not original_id:
            return ""
        topic_id = self.resolve_topic_id(original_id)
        name = name or topic_id.replace("_", " ").title()
        existing_aliases = self._aliases_for_topic(topic_id)
        merged_aliases = sorted({
            self.create_topic_id(alias)
            for alias in [original_id, *(aliases or [])]
            if self.create_topic_id(alias) and self.create_topic_id(alias) != topic_id
        } | set(existing_aliases))
        aliases_json = self._json(merged_aliases)
        self.cursor.execute(
            """
            INSERT INTO topics (id, name, description, aliases_json, created_from, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=COALESCE(excluded.name, topics.name),
                description=COALESCE(excluded.description, topics.description),
                aliases_json=CASE
                    WHEN excluded.aliases_json != '[]' THEN excluded.aliases_json
                    ELSE topics.aliases_json
                END,
                confidence=MAX(COALESCE(topics.confidence, 0), COALESCE(excluded.confidence, 0))
            """,
            (topic_id, name, description, aliases_json, created_from, confidence),
        )
        self.conn.commit()
        return topic_id

    def upsert_topic_edge(
        self,
        topic1: str,
        topic2: str,
        relation_type: str,
        confidence: float = 0.5,
        evidence: str | None = None,
        session_id: str | None = None,
    ):
        topic1 = self.upsert_topic(topic1)
        topic2 = self.upsert_topic(topic2)
        relation_type = self.create_topic_id(relation_type)
        if not topic1 or not topic2 or topic1 == topic2:
            return False
        confidence = max(0.0, min(1.0, float(confidence)))
        self.cursor.execute(
            """
            INSERT INTO topic_edges
                (topic1, topic2, relation_type, confidence, evidence, created_from_session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic1, topic2, relation_type) DO UPDATE SET
                confidence=MAX(COALESCE(topic_edges.confidence, 0), excluded.confidence),
                evidence=COALESCE(excluded.evidence, topic_edges.evidence),
                created_from_session_id=COALESCE(excluded.created_from_session_id, topic_edges.created_from_session_id)
            """,
            (topic1, topic2, relation_type, confidence, evidence, session_id),
        )
        self.conn.commit()
        return True

    def abandon_active_question_sessions(self, user_id: str):
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
        self.cursor.execute(
            """
            UPDATE learning_sessions
            SET conversation_path = ?
            WHERE id = ? AND status = 'active'
            """,
            (conversation_path, session_id),
        )
        self.conn.commit()

    def find_learning_session_by_conversation(self, user_id: str, conversation_path: str) -> str | None:
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

    def insert_semantic_memory(
        self,
        user_id: str,
        session_id: str,
        collection: str,
        topic_id: str,
        text: str,
        extraction_prompt_version: str,
    ) -> str:
        memory_id = self._new_id("mem")
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

    def live_semantic_memory_ids(self, user_id: str, session_id: str, collection: str | None = None) -> list[str]:
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

    def write_audit_log(
        self,
        user_id: str,
        session_id: str | None,
        profile_backup_path: str | None,
        conversation_path: str | None,
        summary: str,
        changes: dict,
    ):
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

    ### Retrieval
    def get_related_topics_pretty(self, topic_names: list[str]):
        related = self.get_related_topics(topic_names)
        pretty = []
        for topic1, topic2, relation in related:
            pretty.append(f"{topic1} --{relation}--> {topic2}")
        return "\n".join(pretty)

    def get_related_topics(self, topic_names: list[str]):
        placeholders = ','.join('?' for _ in topic_names)
        query = f"""
        SELECT topic1, topic2, relation_type FROM topic_edges
        WHERE topic1 IN ({placeholders})
        OR topic2 IN ({placeholders})
        """
        self.cursor.execute(query, topic_names + topic_names)
        return self.cursor.fetchall()
    
    def get_topics_from_related_asks(self, user_id: str, related_asks: list[str]) -> list[str]:
        placeholders = ','.join('?' for _ in related_asks)
        query = f"""
        SELECT DISTINCT tc.topic_id FROM topic_context tc
        JOIN events e ON tc.context_id = e.id AND tc.context_type = e.type
        WHERE e.user_id = ?
        AND e.content IN ({placeholders})
        """
        self.cursor.execute(query, (user_id, *related_asks))
        return [row[0] for row in self.cursor.fetchall()]
        


def gen_dummy_data():
    db = SQLDatabase()
    # Populate topics and edge with dummy data related to inductance
    db.cursor.execute("INSERT INTO topics (id, name, description) VALUES ('inductance', 'Inductance', 'The property of a conductor by which a change in current induces an electromotive force.')")
    db.cursor.execute("INSERT INTO topics (id, name, description) VALUES ('spin', 'Spin', 'An intrinsic form of angular momentum carried by elementary particles.')")
    db.cursor.execute(f"INSERT INTO topic_edges (topic1, topic2, relation_type) VALUES ('spin', 'inductance', {RelationType.PREREQUISITE})")
    db.conn.commit() 



if __name__ == "__main__":
    # gen_dummy_data()
    get_related_topics = SQLDatabase().get_related_topics(['inductance'])
    print("Related topics to inductance:", get_related_topics)
    
