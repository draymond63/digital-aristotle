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
        CREATE TABLE IF NOT EXISTS learning_goals (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            target TEXT NOT NULL,
            target_topic_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            summary TEXT,
            next_step TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS syllabi (
            id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS syllabus_items (
            id TEXT PRIMARY KEY,
            syllabus_id TEXT NOT NULL,
            goal_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            title TEXT NOT NULL,
            objective TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            summary TEXT,
            updated_at TEXT NOT NULL
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS goal_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            goal_id TEXT,
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
        CREATE TABLE IF NOT EXISTS goal_progress_events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            goal_id TEXT,
            session_id TEXT,
            event_type TEXT NOT NULL,
            content TEXT,
            evidence TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS question_goal_links (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            question_session_id TEXT NOT NULL,
            goal_id TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence TEXT,
            created_at TEXT NOT NULL
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS update_audit_log (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT,
            goal_id TEXT,
            profile_backup_path TEXT,
            conversation_path TEXT,
            summary TEXT,
            changes_json TEXT,
            created_at TEXT NOT NULL
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
        self.cursor.execute("SELECT id FROM topics WHERE id = ?", (topic_id,))
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
        self.cursor.execute("UPDATE learning_goals SET target_topic_id = ? WHERE target_topic_id = ?", (target_id, source_id))
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

    def create_learning_goal(
        self,
        user_id: str,
        title: str,
        target: str,
        target_topic_id: str | None = None,
        target_topic_name: str | None = None,
    ):
        goal_id = self._new_id("goal")
        target_topic_id = self.upsert_topic(
            target_topic_id or target,
            name=target_topic_name or title,
            aliases=[target, title],
        )
        self.cursor.execute(
            f"""
            INSERT INTO learning_goals
                (id, user_id, title, target, target_topic_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', {self._now_sql()}, {self._now_sql()})
            """,
            (goal_id, user_id, title, target, target_topic_id),
        )
        self.conn.commit()
        return goal_id

    def create_syllabus(self, goal_id: str, title: str, items: list[dict]):
        syllabus_id = self._new_id("syl")
        self.cursor.execute(
            f"""
            INSERT INTO syllabi (id, goal_id, title, created_at, updated_at)
            VALUES (?, ?, ?, {self._now_sql()}, {self._now_sql()})
            """,
            (syllabus_id, goal_id, title),
        )
        for index, item in enumerate(items, start=1):
            self.cursor.execute(
                f"""
                INSERT INTO syllabus_items
                    (id, syllabus_id, goal_id, position, title, objective, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', {self._now_sql()})
                """,
                (
                    self._new_id("item"),
                    syllabus_id,
                    goal_id,
                    index,
                    item.get("title", f"Milestone {index}"),
                    item.get("objective", ""),
                ),
            )
        self.conn.commit()
        return syllabus_id

    def get_goal(self, goal_id: str):
        self.cursor.execute("SELECT * FROM learning_goals WHERE id = ?", (goal_id,))
        return self.row_to_dict(self.cursor.fetchone())

    def get_active_goals(self, user_id: str):
        self.cursor.execute(
            """
            SELECT * FROM learning_goals
            WHERE user_id = ? AND status = 'active'
            ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def abandon_active_question_sessions(self, user_id: str):
        self.cursor.execute(
            """
            UPDATE goal_sessions
            SET status = 'abandoned', ended_at = datetime('now')
            WHERE user_id = ? AND session_type = 'question' AND status = 'active'
            """,
            (user_id,),
        )
        self.conn.commit()

    def get_recent_active_goal(self, user_id: str):
        goals = self.get_active_goals(user_id)
        return goals[0] if goals else None

    def get_syllabus_items(self, goal_id: str):
        self.cursor.execute(
            """
            SELECT * FROM syllabus_items
            WHERE goal_id = ?
            ORDER BY position ASC
            """,
            (goal_id,),
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_current_syllabus_item(self, goal_id: str):
        self.cursor.execute(
            """
            SELECT * FROM syllabus_items
            WHERE goal_id = ? AND status != 'done'
            ORDER BY position ASC
            LIMIT 1
            """,
            (goal_id,),
        )
        row = self.cursor.fetchone()
        if row:
            return dict(row)
        items = self.get_syllabus_items(goal_id)
        return items[-1] if items else None

    def update_syllabus_item(self, item_id: str, status: str | None = None, summary: str | None = None):
        if status is None and summary is None:
            return
        assignments = ["updated_at = datetime('now')"]
        values = []
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if summary is not None:
            assignments.append("summary = ?")
            values.append(summary)
        values.append(item_id)
        self.cursor.execute(
            f"UPDATE syllabus_items SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        self.conn.commit()

    def touch_goal(self, goal_id: str, summary: str | None = None, next_step: str | None = None, status: str | None = None):
        assignments = ["updated_at = datetime('now')"]
        values = []
        if summary is not None:
            assignments.append("summary = ?")
            values.append(summary)
        if next_step is not None:
            assignments.append("next_step = ?")
            values.append(next_step)
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        values.append(goal_id)
        self.cursor.execute(
            f"UPDATE learning_goals SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        self.conn.commit()

    def create_goal_session(self, user_id: str, session_type: str, goal_id: str | None = None, metadata: dict | None = None):
        session_id = self._new_id("sess")
        self.cursor.execute(
            f"""
            INSERT INTO goal_sessions
                (id, user_id, goal_id, session_type, status, started_at, metadata_json)
            VALUES (?, ?, ?, ?, 'active', {self._now_sql()}, ?)
            """,
            (session_id, user_id, goal_id, session_type, self._json(metadata)),
        )
        self.conn.commit()
        return session_id

    def finish_goal_session(
        self,
        session_id: str,
        conversation_path: str | None = None,
        summary: str | None = None,
        next_step: str | None = None,
        status: str = "done",
    ):
        self.cursor.execute(
            f"""
            UPDATE goal_sessions
            SET status = ?, ended_at = {self._now_sql()}, conversation_path = ?,
                summary = ?, next_step = ?
            WHERE id = ?
            """,
            (status, conversation_path, summary, next_step, session_id),
        )
        self.conn.commit()

    def save_goal_session_progress(self, session_id: str, conversation_path: str):
        self.cursor.execute(
            """
            UPDATE goal_sessions
            SET conversation_path = ?
            WHERE id = ? AND status = 'active'
            """,
            (conversation_path, session_id),
        )
        self.conn.commit()

    def log_progress_event(
        self,
        user_id: str,
        event_type: str,
        content: str,
        goal_id: str | None = None,
        session_id: str | None = None,
        evidence: str | None = None,
        metadata: dict | None = None,
    ):
        event_id = self._new_id("event")
        self.cursor.execute(
            f"""
            INSERT INTO goal_progress_events
                (id, user_id, goal_id, session_id, event_type, content, evidence, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, {self._now_sql()}, ?)
            """,
            (event_id, user_id, goal_id, session_id, event_type, content, evidence, self._json(metadata)),
        )
        self.conn.commit()
        return event_id

    def link_question_to_goal(self, user_id: str, question_session_id: str, goal_id: str, confidence: float, evidence: str):
        link_id = self._new_id("link")
        self.cursor.execute(
            f"""
            INSERT INTO question_goal_links
                (id, user_id, question_session_id, goal_id, confidence, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, {self._now_sql()})
            """,
            (link_id, user_id, question_session_id, goal_id, confidence, evidence),
        )
        self.conn.commit()
        return link_id

    def write_audit_log(
        self,
        user_id: str,
        session_id: str | None,
        goal_id: str | None,
        profile_backup_path: str | None,
        conversation_path: str | None,
        summary: str,
        changes: dict,
    ):
        audit_id = self._new_id("audit")
        self.cursor.execute(
            f"""
            INSERT INTO update_audit_log
                (id, user_id, session_id, goal_id, profile_backup_path, conversation_path, summary, changes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, {self._now_sql()})
            """,
            (
                audit_id,
                user_id,
                session_id,
                goal_id,
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
    
