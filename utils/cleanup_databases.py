from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "aristotle.db"
CHROMA_PATH = DATA_DIR / "chroma"
BACKUP_ROOT = DATA_DIR / "db_backups"

PROBE_USERS = {"codex", "onboarding-feel-test", "onboarding_feel_test", "tester"}
PROFILE_PROBE_PREFIXES = ("codex", "onboarding-feel-test", "onboarding_feel_test", "tester")
CONVERSATION_PROBE_PREFIXES = (
    "codex-",
    "onboarding-",
    "onboarding-feel-test",
)

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


def timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds").replace(":", "-")


def ensure_under_data(path: Path) -> Path:
    resolved = path.resolve()
    data_root = DATA_DIR.resolve()
    if resolved != data_root and data_root not in resolved.parents:
        raise RuntimeError(f"Refusing to delete outside data/: {resolved}")
    return resolved


def copy_if_exists(source: Path, target_root: Path):
    if not source.exists():
        return
    target = target_root / source.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)


def make_backup() -> Path:
    backup_dir = BACKUP_ROOT / f"database-cleanup-{timestamp()}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    copy_if_exists(DB_PATH, backup_dir)
    copy_if_exists(CHROMA_PATH, backup_dir)
    copy_if_exists(DATA_DIR / "profiles", backup_dir)
    copy_if_exists(DATA_DIR / "conversations", backup_dir)
    return backup_dir


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def delete_probe_sql(conn: sqlite3.Connection) -> dict[str, int]:
    deleted: dict[str, int] = {}
    deleted_goal_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM learning_goals WHERE user_id IN ({})".format(
                ",".join("?" for _ in PROBE_USERS)
            ),
            tuple(PROBE_USERS),
        )
    ]
    deleted_session_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM goal_sessions WHERE user_id IN ({})".format(
                ",".join("?" for _ in PROBE_USERS)
            ),
            tuple(PROBE_USERS),
        )
    ]

    if deleted_goal_ids:
        placeholders = ",".join("?" for _ in deleted_goal_ids)
        before = conn.total_changes
        conn.execute(f"DELETE FROM syllabus_items WHERE goal_id IN ({placeholders})", tuple(deleted_goal_ids))
        deleted["syllabus_items"] = conn.total_changes - before
        before = conn.total_changes
        conn.execute(f"DELETE FROM syllabi WHERE goal_id IN ({placeholders})", tuple(deleted_goal_ids))
        deleted["syllabi"] = conn.total_changes - before
    else:
        deleted["syllabus_items"] = 0
        deleted["syllabi"] = 0

    for table, predicate in reversed(USER_TABLE_PREDICATES.items()):
        if not table_exists(conn, table):
            continue
        before = conn.total_changes
        for user_id in PROBE_USERS:
            conn.execute(f"DELETE FROM {table} WHERE {predicate}", (user_id,))
        deleted[table] = conn.total_changes - before

    if deleted_session_ids and table_exists(conn, "topic_edges"):
        placeholders = ",".join("?" for _ in deleted_session_ids)
        before = conn.total_changes
        conn.execute(
            f"DELETE FROM topic_edges WHERE created_from_session_id IN ({placeholders})",
            tuple(deleted_session_ids),
        )
        deleted["topic_edges_from_probe_sessions"] = conn.total_changes - before

    if deleted_session_ids and table_exists(conn, "topics"):
        placeholders = ",".join("?" for _ in deleted_session_ids)
        before = conn.total_changes
        conn.execute(
            f"DELETE FROM topics WHERE created_from IN ({placeholders})",
            tuple(deleted_session_ids),
        )
        deleted["topics_from_probe_sessions"] = conn.total_changes - before

    return deleted


def delete_legacy_sql(conn: sqlite3.Connection) -> dict[str, int]:
    deleted = {}
    if table_exists(conn, "events"):
        before = conn.total_changes
        conn.execute("DELETE FROM events WHERE session_id IS NULL")
        deleted["legacy_events_without_session"] = conn.total_changes - before
    if table_exists(conn, "topic_context"):
        before = conn.total_changes
        conn.execute(
            """
            DELETE FROM topic_context
            WHERE context_id NOT IN (SELECT id FROM goal_sessions)
            """
        )
        deleted["orphan_topic_context"] = conn.total_changes - before
    return deleted


def prune_orphan_graph(conn: sqlite3.Connection) -> dict[str, int]:
    deleted = {}
    if table_exists(conn, "topic_edges"):
        before = conn.total_changes
        conn.execute(
            """
            DELETE FROM topic_edges
            WHERE topic1 NOT IN (SELECT id FROM topics)
               OR topic2 NOT IN (SELECT id FROM topics)
               OR topic1 = topic2
               OR (evidence IS NULL AND created_from_session_id IS NULL)
            """
        )
        deleted["orphan_topic_edges"] = conn.total_changes - before

    if table_exists(conn, "topics"):
        before = conn.total_changes
        conn.execute(
            """
            DELETE FROM topics
            WHERE id NOT IN (SELECT target_topic_id FROM learning_goals WHERE target_topic_id IS NOT NULL)
              AND id NOT IN (SELECT topic_id FROM mastery_history WHERE topic_id IS NOT NULL)
              AND id NOT IN (SELECT topic_id FROM topic_context WHERE topic_id IS NOT NULL)
              AND id NOT IN (SELECT topic1 FROM topic_edges)
              AND id NOT IN (SELECT topic2 FROM topic_edges)
            """
        )
        deleted["unreferenced_topics"] = conn.total_changes - before
    return deleted


def cleanup_sql(dry_run: bool) -> dict:
    if not DB_PATH.exists():
        return {"note": "No SQLite database found."}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    before = {
        row["name"]: conn.execute(f"SELECT COUNT(*) FROM {row['name']}").fetchone()[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row["name"] != "sqlite_sequence"
    }
    if dry_run:
        conn.close()
        return {"before": before, "dry_run": True}

    deleted = {}
    deleted.update(delete_probe_sql(conn))
    deleted.update(delete_legacy_sql(conn))
    deleted.update(prune_orphan_graph(conn))
    conn.commit()
    conn.execute("VACUUM")
    after = {
        row["name"]: conn.execute(f"SELECT COUNT(*) FROM {row['name']}").fetchone()[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row["name"] != "sqlite_sequence"
    }
    conn.close()
    return {"before": before, "deleted": deleted, "after": after}


def cleanup_chroma(dry_run: bool) -> dict:
    if not CHROMA_PATH.exists():
        return {"note": "No Chroma database found."}
    from chromadb import PersistentClient

    client = PersistentClient(path=str(CHROMA_PATH))
    report = {}
    for collection in list(client.list_collections()):
        data = collection.get(include=["metadatas"])
        ids = data.get("ids", [])
        metadatas = data.get("metadatas", [])
        missing_user_ids = [
            item_id
            for item_id, metadata in zip(ids, metadatas)
            if not metadata or not metadata.get("user_id")
        ]
        probe_user_ids = [
            item_id
            for item_id, metadata in zip(ids, metadatas)
            if metadata and metadata.get("user_id") in PROBE_USERS
        ]
        to_delete = sorted(set(missing_user_ids + probe_user_ids))
        report[collection.name] = {
            "before": len(ids),
            "missing_user_id": len(missing_user_ids),
            "probe_user": len(probe_user_ids),
            "deleted": 0 if dry_run else len(to_delete),
        }
        if not dry_run and to_delete:
            collection.delete(ids=to_delete)
        if collection.name == "test":
            report[collection.name]["delete_collection"] = True
            if not dry_run:
                client.delete_collection(collection.name)
    return report


def delete_path(path: Path) -> bool:
    resolved = ensure_under_data(path)
    if not resolved.exists():
        return False
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
    return True


def cleanup_files(dry_run: bool) -> dict:
    targets: list[Path] = []
    profiles = DATA_DIR / "profiles"
    if profiles.exists():
        for profile in profiles.glob("*.yaml"):
            if profile.stem.startswith(PROFILE_PROBE_PREFIXES):
                targets.append(profile)
    profile_backups = DATA_DIR / "profile_backups"
    if profile_backups.exists():
        for folder in profile_backups.iterdir():
            if folder.name.startswith(PROFILE_PROBE_PREFIXES):
                targets.append(folder)
    conversations = DATA_DIR / "conversations"
    if conversations.exists():
        for conversation in conversations.glob("*.json"):
            if conversation.name.startswith(CONVERSATION_PROBE_PREFIXES):
                targets.append(conversation)
    report = {"targets": [str(path.relative_to(ROOT)) for path in targets], "deleted": 0}
    if not dry_run:
        for target in targets:
            if delete_path(target):
                report["deleted"] += 1
    return report


def main():
    parser = argparse.ArgumentParser(description="Back up and remove known-useless local AI Teacher database data.")
    parser.add_argument("--dry-run", action="store_true", help="Report cleanup targets without deleting them.")
    args = parser.parse_args()

    backup_dir = None if args.dry_run else make_backup()
    report = {
        "backup_dir": str(backup_dir) if backup_dir else None,
        "dry_run": args.dry_run,
        "sqlite": cleanup_sql(args.dry_run),
        "chroma": cleanup_chroma(args.dry_run),
        "files": cleanup_files(args.dry_run),
    }
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
