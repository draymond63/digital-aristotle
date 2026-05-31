from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from brains.data.db_vector import Collection, SemanticDatabase


DEFAULT_USERS = (
    "eval_philosophy",
    "eval_statistics",
    "eval_machine_learning",
    "eval_web_architecture",
    "eval_history",
)
MAX_FIELD_LENGTH = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect ai-teacher subagent eval persistence.")
    parser.add_argument(
        "--eval-path",
        help="Eval JSON artifact to inspect. Defaults to the newest data/evals/multi-agent-knowledge-*.json file.",
    )
    parser.add_argument(
        "--users",
        help="Comma-separated user IDs to inspect. Defaults to users found in the eval artifact, or default eval users.",
    )
    parser.add_argument(
        "--vector-limit",
        type=int,
        default=3,
        help="Number of sample vector docs to print per user and collection.",
    )
    return parser.parse_args()


def latest_eval_path() -> Path:
    candidates = sorted(Path("data/evals").glob("multi-agent-knowledge-*.json"))
    if not candidates:
        raise FileNotFoundError("No data/evals/multi-agent-knowledge-*.json files found")
    return candidates[-1]


def load_eval(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_users(args: argparse.Namespace, data: list[dict]) -> tuple[str, ...]:
    if args.users:
        return tuple(item.strip() for item in args.users.split(",") if item.strip())
    users = tuple(result.get("user_id", "") for result in data if result.get("user_id"))
    return users or DEFAULT_USERS


def print_eval_json(path: Path, data: list[dict]) -> None:
    print(f"EVAL JSON {path}")
    for result in data:
        finalization = result["finalization"]
        print(f"- {result['user_id']}")
        print(f"  summary: {finalization['summary']}")
        print(f"  next: {finalization['next_step']}")
        print(f"  topics_updated: {finalization['topics_updated']}")
        print(f"  memories_saved: {finalization['memories_saved']}")
        print(f"  graph_changes: {finalization['graph_changes']}")
        print(f"  profile_topics: {list(result['profile']['topics'].keys())}")


def print_sql(users: tuple[str, ...]) -> None:
    db = sqlite3.connect("data/aristotle.db")
    db.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in users)

    print("\nSQL")
    for table in ("learning_sessions", "update_audit_log", "mastery_history", "semantic_memories"):
        rows = db.execute(
            f"SELECT * FROM {table} WHERE user_id IN ({placeholders}) ORDER BY rowid",
            users,
        ).fetchall()
        print(f"- {table}: {len(rows)}")
        for row in rows[-12:]:
            print(f"  {compact_row(dict(row))}")
    db.close()


def print_vector(users: tuple[str, ...], vector_limit: int) -> None:
    db = SemanticDatabase()
    print("\nVECTOR")
    for collection_name in Collection:
        collection = db.collection(collection_name)
        total = collection.count()
        print(f"- {collection_name.value}: total {total}")
        for user_id in users:
            result = collection.get(where={"user_id": {"$eq": user_id}}, limit=50)
            docs = result.get("documents") or []
            print(f"  {user_id}: {len(docs)}")
            for doc, metadata in zip(docs[:vector_limit], result.get("metadatas") or []):
                print(f"    {metadata}: {doc[:180]}")


def compact_row(row: dict) -> dict:
    compacted = {}
    for key, value in row.items():
        if isinstance(value, str) and len(value) > MAX_FIELD_LENGTH:
            compacted[key] = f"{value[:MAX_FIELD_LENGTH]}..."
        else:
            compacted[key] = value
    return compacted


def main() -> None:
    args = parse_args()
    eval_path = Path(args.eval_path) if args.eval_path else latest_eval_path()
    data = load_eval(eval_path)
    users = selected_users(args, data)
    print_eval_json(eval_path, data)
    print_sql(users)
    print_vector(users, args.vector_limit)


if __name__ == "__main__":
    main()
