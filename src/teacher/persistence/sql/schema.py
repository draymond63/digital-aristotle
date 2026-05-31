import sqlite3
from pathlib import Path


def init_db(path: Path):
    """Initialize the SQLite schema and additive migrations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        created_at TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS topics (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS topic_edges (
        topic1 TEXT,
        topic2 TEXT,
        relation_type TEXT,
        PRIMARY KEY (topic1, topic2, relation_type)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS topic_context (
        topic_id TEXT,
        context_type TEXT,
        context_id TEXT,
        PRIMARY KEY (topic_id, context_type, context_id)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS lessons (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        topic_id TEXT,
        started_at TEXT,
        ended_at TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        type TEXT,
        topic_id TEXT,
        content TEXT,
        timestamp TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS mastery_history (
        user_id TEXT,
        topic_id TEXT,
        mastery REAL,
        timestamp TEXT
    )
    """)

    add_column_if_missing(conn, "topics", "aliases_json", "TEXT")
    add_column_if_missing(conn, "topics", "created_from", "TEXT")
    add_column_if_missing(conn, "topics", "confidence", "REAL DEFAULT 0.5")
    add_column_if_missing(conn, "topic_edges", "confidence", "REAL DEFAULT 0.5")
    add_column_if_missing(conn, "topic_edges", "evidence", "TEXT")
    add_column_if_missing(conn, "topic_edges", "created_from_session_id", "TEXT")
    add_column_if_missing(conn, "events", "session_id", "TEXT")
    add_column_if_missing(conn, "events", "metadata_json", "TEXT")
    add_column_if_missing(conn, "mastery_history", "intuition", "REAL")
    add_column_if_missing(conn, "mastery_history", "details", "REAL")
    add_column_if_missing(conn, "mastery_history", "confidence", "REAL")
    add_column_if_missing(conn, "mastery_history", "evidence", "TEXT")

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


def add_column_if_missing(conn, table: str, column: str, declaration: str):
    """Add one SQLite column when it does not already exist."""
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in c.fetchall()}
    if column not in columns:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
