from __future__ import annotations

import logging

from teacher.persistence.sql import SQLDatabase
from teacher.persistence.vector import MemoryKind, SemanticDatabase
from teacher.session.types import ExtractedMemory
from teacher.utils.identifiers import normalize_identifier


logger = logging.getLogger(__name__)
MEMORY_EXTRACTION_PROMPT_VERSION = "memory_v3_bucketed_partial_lean_sql"


class SemanticMemoryStore:
    """Coordinate SQL and vector persistence for semantic memories."""

    def __init__(self, sql_db: SQLDatabase, vector_db: SemanticDatabase):
        """Initialize SQL and vector stores."""
        self.sql_db = sql_db
        self.vector_db = vector_db

    def save_session_memories(
        self,
        user_id: str,
        session_id: str | None,
        memories: list[ExtractedMemory],
        source: str | None = None,
    ) -> int:
        """Save validated memories for one completed session."""
        if not session_id:
            logger.warning(f"Skipping {len(memories)} memories without active session for user {user_id}")
            return 0
        saved = 0
        for memory in memories:
            text = memory.text.strip()
            if not text or float(memory.confidence) < 0.35:
                logger.warning(f"Skipping invalid or weak memory for user {user_id}: {memory.json_data()!r}")
                continue
            topic_id = normalize_identifier(memory.topic_id)
            if not topic_id:
                logger.warning(f"Skipping memory without topic for user {user_id}: {memory.json_data()!r}")
                continue
            memory_id = self.sql_db._new_id("mem")
            metadata = self._metadata(user_id, session_id, memory_id, topic_id, memory.kind, source)
            try:
                self.vector_db.add(memory.kind.collection, ids=[memory_id], documents=[text], metadatas=[metadata])
                self.sql_db.insert_semantic_memory(
                    user_id=user_id,
                    session_id=session_id,
                    collection=memory.kind.value,
                    topic_id=topic_id,
                    text=text,
                    extraction_prompt_version=MEMORY_EXTRACTION_PROMPT_VERSION,
                    memory_id=memory_id,
                )
            except Exception:
                self.vector_db.delete_ids(memory.kind.collection, [memory_id])
                logger.exception(
                    f"Failed to save memory for user {user_id} "
                    f"in collection {memory.kind.value}: {memory.json_data()!r}"
                )
                continue
            saved += 1
        return saved

    @staticmethod
    def _metadata(
        user_id: str,
        session_id: str,
        memory_id: str,
        topic_id: str,
        memory_type: MemoryKind,
        source: str | None,
    ) -> dict:
        """Build metadata shared between SQL and vector stores."""
        metadata = {
            "user_id": user_id,
            "session_id": session_id,
            "semantic_memory_id": memory_id,
            "topic_id": topic_id,
            "memory_type": memory_type.memory_type,
        }
        if source:
            metadata["source"] = source
        return metadata

    def existing_memory_ids(self, user_id: str, session_id: str) -> dict[str, list[str]]:
        """Return SQL and vector memory IDs grouped by collection."""
        return {
            collection.value: sorted(
                set(self.sql_db.live_semantic_memory_ids(user_id, session_id, collection.value))
                | set(self.vector_db.ids_for_metadata(collection, user_id=user_id, session_id=session_id))
            )
            for collection in MemoryKind.vector_collections()
        }

    def replace_session_memories(
        self,
        user_id: str,
        session_id: str,
        memories: list[ExtractedMemory],
        source: str | None = None,
    ) -> int:
        """Replace all live memories for a session."""
        existing_ids = self.existing_memory_ids(user_id, session_id)
        for collection in MemoryKind.vector_collections():
            self.vector_db.delete_ids(collection, existing_ids[collection.value])
        self.sql_db.mark_semantic_memories_replaced(user_id, session_id)
        return self.save_session_memories(user_id, session_id, memories, source=source)
