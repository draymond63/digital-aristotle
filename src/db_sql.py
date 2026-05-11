import sqlite3
from pathlib import Path


class SQLDatabase:
    def __init(self, path="data/aristotle.db"):
        source = Path(path)
        if source.is_file():
            self.conn = sqlite3.connect(path)
        else:
            self.conn = self.init_db(path)
        

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
            parent TEXT,
            child TEXT,
            relation_type TEXT, -- prerequisite | related | subtopic
            PRIMARY KEY (parent, child, relation_type)
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


    def add_user(sel, user_id: str):
        



if __name__ == "__main__":
    SQLDatabase()