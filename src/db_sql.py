import sqlite3
from pathlib import Path


class SQLDatabase:
    def __init__(self, path="data/aristotle.db"):
        source = Path(path)
        if source.is_file():
            self.conn = sqlite3.connect(path)
        else:
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

    ### Retrieval

    def get_related_topics(self, topic_names: list[str]):
        placeholders = ','.join('?' for _ in topic_names)
        query = f"""
        SELECT topic2, relation_type FROM topic_edges
        WHERE topic1 IN ({placeholders})
        OR topic2 IN ({placeholders})
        """
        self.cursor.execute(query, topic_names)
        return self.cursor.fetchall()



def gen_dummy_data():
    db = SQLDatabase()
    # Populate topics and edge with dummy data related to inductance
    db.cursor.execute("INSERT INTO topics (id, name, description) VALUES ('inductance', 'Inductance', 'The property of a conductor by which a change in current induces an electromotive force.')")
    db.cursor.execute("INSERT INTO topics (id, name, description) VALUES ('spin', 'Spin', 'An intrinsic form of angular momentum carried by elementary particles.')")
    db.cursor.execute("INSERT INTO topic_edges (topic1, topic2, relation_type) VALUES ('spin', 'inductance', 'prerequisite')")
    db.conn.commit() 



if __name__ == "__main__":
    gen_dummy_data()
