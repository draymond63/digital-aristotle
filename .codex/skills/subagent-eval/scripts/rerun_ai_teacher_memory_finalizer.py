from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from brains.comms.agent_base import Conversation
from brains.session import LearningSession
from brains.session_types import ExtractedMemory, SessionMemoryExtractionResponse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run or apply memory finalizer reruns for ai-teacher evals.")
    parser.add_argument(
        "--eval-path",
        action="append",
        help="Eval JSON artifact to process. May be passed more than once.",
    )
    parser.add_argument(
        "--rerun-report",
        help="Existing memory finalizer rerun report to apply or inspect without model calls.",
    )
    parser.add_argument(
        "--users",
        help="Comma-separated user IDs to process from the eval artifacts. Defaults to all.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/evals",
        help="Directory for the rerun JSON report.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Replace existing vector memories for each resolved session. Omit for dry-run only.",
    )
    return parser.parse_args()


def selected_users(args: argparse.Namespace) -> set[str] | None:
    if not args.users:
        return None
    return {item.strip() for item in args.users.split(",") if item.strip()}


def load_eval(path: Path, users: set[str] | None) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = json.load(f)
    if users is None:
        return rows
    return [row for row in rows if row["user_id"] in users]


def extract_memories(user_id: str, conversation_path: str) -> tuple[LearningSession, list[ExtractedMemory]]:
    session = LearningSession(user_id=user_id, abandon_active=False)
    session.conversation = Conversation.load(conversation_path)
    result = session.run_task_json(
        session.memory_extraction_task,
        session.conversation,
        visible=False,
        default=SessionMemoryExtractionResponse(),
        error_message=f"Failed memory finalizer rerun for {user_id} from {conversation_path}",
    )
    return session, session._dedupe_memories(result.extracted_memories())


def memory_from_json(data: dict) -> ExtractedMemory:
    return ExtractedMemory.model_validate(data)


def report_rows(path: Path, users: set[str] | None) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        report = json.load(f)
    rows = []
    for source in report:
        for row in source["results"]:
            if users is None or row["user_id"] in users:
                rows.append(row)
    return rows


def process_rerun_report(args: argparse.Namespace) -> list[dict]:
    users = selected_users(args)
    output_results = []
    for row in report_rows(Path(args.rerun_report), users):
        user_id = row["user_id"]
        conversation_path = row["conversation_path"]
        session = LearningSession(user_id=user_id, abandon_active=False)
        session_id = row.get("session_id") or session.sql_db.find_learning_session_by_conversation(
            user_id,
            conversation_path,
        )
        memories = [memory_from_json(memory) for memory in row["memories"]]
        stale_ids = session.memory_store.existing_memory_ids(user_id, session_id) if session_id else {}
        if args.apply:
            if not session_id:
                raise RuntimeError(f"Could not resolve session id for {user_id}: {conversation_path}")
            session.memory_store.replace_session_memories(
                user_id,
                session_id,
                memories,
                source="memory_finalizer_rerun",
            )
        item = {
            "user_id": user_id,
            "conversation_path": conversation_path,
            "session_id": session_id,
            "applied": bool(args.apply),
            "memory_counts": row["memory_counts"],
            "total_memories": row["total_memories"],
            "existing_memory_ids": stale_ids,
            "memories": row["memories"],
        }
        output_results.append(item)
        print(f"# {user_id} total={row['total_memories']} counts={row['memory_counts']} applied={args.apply}")
        if stale_ids:
            print(f"existing_memory_ids={sum(len(ids) for ids in stale_ids.values())}")
        session.sql_db.close()
    return [{"source_rerun_report": args.rerun_report, "results": output_results}]


def main() -> None:
    args = parse_args()
    if not args.eval_path and not args.rerun_report:
        raise ValueError("Pass --eval-path or --rerun-report")
    if args.eval_path and args.rerun_report:
        raise ValueError("Pass either --eval-path or --rerun-report, not both")
    if args.rerun_report:
        all_results = process_rerun_report(args)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        mode = "applied" if args.apply else "dry-run"
        output = output_dir / (
            f"memory-finalizer-{mode}-{datetime.now().isoformat(timespec='seconds').replace(':', '-')}.json"
        )
        output.write_text(json.dumps(all_results, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"output={output}")
        return

    users = selected_users(args)
    all_results = []
    for eval_path_text in args.eval_path:
        eval_path = Path(eval_path_text)
        rows = load_eval(eval_path, users)
        run_results = []
        print(f"## {eval_path}")
        for row in rows:
            user_id = row["user_id"]
            conversation_path = row["finalization"]["conversation_path"]
            session, memories = extract_memories(user_id, conversation_path)
            session_id = session.sql_db.find_learning_session_by_conversation(user_id, conversation_path)
            counts = Counter(memory.kind.memory_type for memory in memories)
            stale_ids = session.memory_store.existing_memory_ids(user_id, session_id) if session_id else {}
            if args.apply:
                if not session_id:
                    raise RuntimeError(f"Could not resolve session id for {user_id}: {conversation_path}")
                session.memory_store.replace_session_memories(
                    user_id,
                    session_id,
                    memories,
                    source="memory_finalizer_rerun",
                )
            item = {
                "user_id": user_id,
                "conversation_path": conversation_path,
                "session_id": session_id,
                "applied": bool(args.apply),
                "memory_counts": dict(sorted(counts.items())),
                "total_memories": len(memories),
                "existing_memory_ids": stale_ids,
                "memories": [memory.json_data() for memory in memories],
            }
            run_results.append(item)
            print(f"# {user_id} total={len(memories)} counts={item['memory_counts']} applied={args.apply}")
            if stale_ids:
                stale_count = sum(len(ids) for ids in stale_ids.values())
                print(f"existing_memory_ids={stale_count}")
            for memory in memories:
                print(f"- {memory.kind.memory_type}: {memory.topic_id}: {memory.text[:170]}")
            print()
            session.sql_db.close()
        all_results.append({"source_eval": str(eval_path), "results": run_results})

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = "applied" if args.apply else "dry-run"
    output = output_dir / (
        f"memory-finalizer-{mode}-{datetime.now().isoformat(timespec='seconds').replace(':', '-')}.json"
    )
    output.write_text(json.dumps(all_results, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"output={output}")


if __name__ == "__main__":
    main()
