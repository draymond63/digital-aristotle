from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from brains.data.profile import normalize_identifier


logger = logging.getLogger(__name__)


DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "aristotle.db"
CHROMA_PATH = DATA_DIR / "chroma"
BACKUP_ROOT = DATA_DIR / "user_reset_backups"

USER_SCOPED_TABLES = [
    "users",
    "events",
    "lessons",
    "mastery_history",
    "learning_goals",
    "goal_sessions",
    "goal_progress_events",
    "question_goal_links",
    "update_audit_log",
]

USER_TABLE_PREDICATES = {
    "users": "id = ?",
    "events": "user_id = ?",
    "lessons": "user_id = ?",
    "mastery_history": "user_id = ?",
    "learning_goals": "user_id = ?",
    "goal_sessions": "user_id = ?",
    "goal_progress_events": "user_id = ?",
    "question_goal_links": "user_id = ?",
    "update_audit_log": "user_id = ?",
}


def user_id_from_telegram_id(telegram_id: str) -> str:
    return normalize_identifier(f"telegram_{telegram_id}")


def timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds").replace(":", "-")


def fetch_rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def user_sql_snapshot(conn: sqlite3.Connection, user_id: str) -> dict[str, list[dict]]:
    snapshot = {}
    for table in USER_SCOPED_TABLES:
        predicate = USER_TABLE_PREDICATES[table]
        snapshot[table] = fetch_rows(conn, f"SELECT * FROM {table} WHERE {predicate}", (user_id,))

    goal_ids = [row["id"] for row in snapshot["learning_goals"]]
    if goal_ids:
        placeholders = ",".join("?" for _ in goal_ids)
        snapshot["syllabi"] = fetch_rows(
            conn,
            f"SELECT * FROM syllabi WHERE goal_id IN ({placeholders})",
            tuple(goal_ids),
        )
        snapshot["syllabus_items"] = fetch_rows(
            conn,
            f"SELECT * FROM syllabus_items WHERE goal_id IN ({placeholders})",
            tuple(goal_ids),
        )
    else:
        snapshot["syllabi"] = []
        snapshot["syllabus_items"] = []
    return snapshot


def copy_if_exists(source: Path, backup_dir: Path):
    if not source.exists():
        return
    try:
        relative_source = source.relative_to(ROOT)
    except ValueError:
        relative_source = Path(source.name)
    target = backup_dir / relative_source
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)


def conversation_files(user_id: str) -> list[Path]:
    conversation_dir = DATA_DIR / "conversations"
    if not conversation_dir.exists():
        return []
    return sorted(conversation_dir.glob(f"{user_id}-*.json"))


def make_backup(user_id: str, conn: sqlite3.Connection) -> Path:
    backup_dir = BACKUP_ROOT / f"{user_id}-{timestamp()}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    copy_if_exists(DB_PATH, backup_dir)
    copy_if_exists(DATA_DIR / "profiles" / f"{user_id}.yaml", backup_dir)
    copy_if_exists(DATA_DIR / "profile_backups" / user_id, backup_dir)
    for path in conversation_files(user_id):
        copy_if_exists(path, backup_dir)

    snapshot = user_sql_snapshot(conn, user_id)
    with (backup_dir / "sql_rows.json").open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, ensure_ascii=True)

    return backup_dir


def delete_sql_rows(conn: sqlite3.Connection, user_id: str) -> dict[str, int]:
    deleted = {}
    goal_ids = [row["id"] for row in conn.execute("SELECT id FROM learning_goals WHERE user_id = ?", (user_id,))]
    if goal_ids:
        placeholders = ",".join("?" for _ in goal_ids)
        before = conn.total_changes
        conn.execute(f"DELETE FROM syllabus_items WHERE goal_id IN ({placeholders})", tuple(goal_ids))
        deleted["syllabus_items"] = conn.total_changes - before
        before = conn.total_changes
        conn.execute(f"DELETE FROM syllabi WHERE goal_id IN ({placeholders})", tuple(goal_ids))
        deleted["syllabi"] = conn.total_changes - before
    else:
        deleted["syllabus_items"] = 0
        deleted["syllabi"] = 0

    for table in reversed(USER_SCOPED_TABLES):
        before = conn.total_changes
        predicate = USER_TABLE_PREDICATES[table]
        conn.execute(f"DELETE FROM {table} WHERE {predicate}", (user_id,))
        deleted[table] = conn.total_changes - before
    conn.commit()
    return deleted


def delete_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def delete_user_files(user_id: str) -> dict[str, int | bool]:
    profile_deleted = delete_path(DATA_DIR / "profiles" / f"{user_id}.yaml")
    profile_backups_deleted = delete_path(DATA_DIR / "profile_backups" / user_id)
    conversations = conversation_files(user_id)
    for path in conversations:
        delete_path(path)
    return {
        "profile_deleted": profile_deleted,
        "profile_backups_deleted": profile_backups_deleted,
        "conversation_files_deleted": len(conversations),
    }


def delete_traceable_chroma_entries(user_id: str, session_ids: list[str]) -> dict[str, int | str]:
    if not CHROMA_PATH.exists():
        return {"deleted": 0, "note": "No Chroma directory."}
    try:
        from chromadb import PersistentClient
        from brains.data.db_vector import Collection
    except Exception as exc:
        logger.exception(f"Could not import Chroma while resetting user {user_id}")
        return {"deleted": 0, "note": f"Could not import Chroma: {exc}"}

    client = PersistentClient(path=str(CHROMA_PATH))
    deleted = 0
    prefixes = tuple(f"{session_id}-" for session_id in session_ids)
    for collection_name in (
        Collection.INSIGHTS,
        Collection.CONFUSIONS,
        Collection.SUCCESSFUL_EXPLANATIONS,
        Collection.LEARNING_PREFERENCES,
        Collection.PREVIOUS_ASKS,
    ):
        collection = client.get_or_create_collection(name=collection_name.value)
        try:
            matching = collection.get(where={"user_id": {"$eq": user_id}}, include=[]).get("ids", [])
        except Exception:
            logger.exception(
                f"Failed to get Chroma entries by user metadata in collection {collection_name.value} "
                f"for user {user_id}"
            )
            matching = []
        if not matching and prefixes:
            ids = collection.get(include=[]).get("ids", [])
            matching = [item_id for item_id in ids if item_id.startswith(prefixes)]
        if matching:
            collection.delete(ids=matching)
            deleted += len(matching)
    return {
        "deleted": deleted,
        "note": "Deleted user-scoped Chroma entries; old previous_asks without metadata may remain.",
    }


def reset_user(telegram_id: str, dry_run: bool = False) -> dict:
    user_id = user_id_from_telegram_id(telegram_id)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    snapshot = user_sql_snapshot(conn, user_id)
    session_ids = [row["id"] for row in snapshot["goal_sessions"]]
    backup_dir = make_backup(user_id, conn)

    report = {
        "telegram_id": telegram_id,
        "user_id": user_id,
        "backup_dir": str(backup_dir),
        "dry_run": dry_run,
        "sql_rows_found": {table: len(rows) for table, rows in snapshot.items()},
        "files_found": {
            "profile": (DATA_DIR / "profiles" / f"{user_id}.yaml").exists(),
            "profile_backups": (DATA_DIR / "profile_backups" / user_id).exists(),
            "conversations": len(conversation_files(user_id)),
        },
    }

    if dry_run:
        conn.close()
        return report

    report["chroma"] = delete_traceable_chroma_entries(user_id, session_ids)
    report["files_deleted"] = delete_user_files(user_id)
    report["sql_rows_deleted"] = delete_sql_rows(conn, user_id)
    conn.close()
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Back up and delete local AI Teacher data for a Telegram user."
    )
    parser.add_argument("telegram_id", help="Numeric Telegram user id, without the telegram_ prefix.")
    parser.add_argument("--dry-run", action="store_true", help="Create a backup and report what would be deleted.")
    args = parser.parse_args()

    report = reset_user(args.telegram_id, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
