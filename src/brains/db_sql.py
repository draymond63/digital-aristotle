import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class EventType:
    SESSION_START = "session_start"
    MASTERY_UPDATE = "mastery_update"


@dataclass
class RelationType:
    PREREQUISITE = "prerequisite"
    RELATED = "related"


class SQLDatabase:
    def __init__(self, path="data/aristotle.db"):
        path = Path(path)
        self.conn = self.init_db(path)
        self.cursor = self.conn.cursor()

    @staticmethod
    def init_db(path: str):
        conn = sqlite3.connect(path)
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

        conn.commit()
        return conn

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
            topic_id = self.create_topic_id(topic)
            # Add topics to topics table
            self.cursor.execute(
                "INSERT OR IGNORE INTO topics (id, name) VALUES (?, ?)",
                (topic_id, topic)
            )
            # Relate topics to session
            self.cursor.execute(
                "INSERT OR IGNORE INTO topic_context (topic_id, context_type, context_id) VALUES (?, ?, ?)",
                (topic_id, EventType.SESSION_START, session_id)
            )
            # Add topics to topic_edges with relation_type "related" (for now, can be refined later)
            self.cursor.execute(
                "INSERT OR IGNORE INTO topic_edges (topic1, topic2, relation_type) VALUES (?, ?, ?)",
                (topic_id, topic_id, RelationType.RELATED)
            )
        self.conn.commit()

    @staticmethod
    def create_topic_id(topic: str):
        return topic.lower().replace(" ", "_")

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
    
