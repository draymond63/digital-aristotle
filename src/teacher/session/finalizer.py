from __future__ import annotations

import json
import logging

from teacher.session.types import (
    ExtractedMemory,
    GraphUpdatesResponse,
    ProfileUpdateGateResponse,
    SessionFinalizationResponse,
    SessionGraphUpdatesResponse,
    SessionMemoryExtractionResponse,
    SessionSummaryResponse,
    SessionTopicUpdatesResponse,
    TopicUpdateResponse,
)
from teacher.utils.identifiers import normalize_identifier


logger = logging.getLogger(__name__)


def dedupe_by(items, key_fn, on_duplicate=None):
    """Return items deduped by a caller-provided key."""
    deduped = []
    seen = set()
    for item in items:
        key = key_fn(item)
        if key in seen:
            if on_duplicate:
                on_duplicate(item)
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


class SessionFinalizerMixin:
    """Extract and apply durable updates from a completed session."""

    def _finalize_updates(self) -> SessionFinalizationResponse:
        """Run all structured finalization tasks."""
        summary_result = self.run_task_json(
            self.summary_task,
            self.conversation,
            visible=False,
            default=SessionSummaryResponse(),
            error_message=f"Failed to run {self.summary_task.name} for user {self.user_id}",
        )
        topic_updates_result = self.run_task_json(
            self.topic_updates_task,
            self.conversation,
            visible=False,
            dynamic_prompts=[
                f"Known global topic graph candidates:\n{json.dumps(self.sql_db.get_topic_summaries(limit=60), ensure_ascii=True)}"
            ],
            default=SessionTopicUpdatesResponse(),
            error_message=f"Failed to run {self.topic_updates_task.name} for user {self.user_id}",
        )
        memories_result = self.run_task_json(
            self.memory_extraction_task,
            self.conversation,
            visible=False,
            default=SessionMemoryExtractionResponse(),
            error_message=f"Failed to run {self.memory_extraction_task.name} for user {self.user_id}",
        )
        graph_updates_result = self.run_task_json(
            self.graph_updates_task,
            self.conversation,
            visible=False,
            dynamic_prompts=[
                f"Known global topic graph candidates:\n{json.dumps(self.sql_db.get_topic_summaries(limit=60), ensure_ascii=True)}"
            ],
            default=SessionGraphUpdatesResponse(),
            error_message=f"Failed to run {self.graph_updates_task.name} for user {self.user_id}",
        )
        return SessionFinalizationResponse(
            summary=summary_result.summary or "summary unavailable because session summary extraction failed",
            next_step=summary_result.next_step or "next step unavailable because session summary extraction failed",
            topic_updates=topic_updates_result.topic_updates,
            memories=self._dedupe_memories(memories_result.extracted_memories()),
            graph_updates=self._limit_graph_updates(graph_updates_result.graph_updates),
        )

    def _dedupe_memories(
        self,
        memories: list[ExtractedMemory],
    ) -> list[ExtractedMemory]:
        """Dedupe extracted memories before persistence."""
        return dedupe_by(
            memories,
            key_fn=lambda memory: (memory.kind, normalize_identifier(memory.topic_id)),
            on_duplicate=lambda memory: logger.warning(
                f"Skipping duplicate memory update for user {self.user_id}: {memory.json_data()!r}"
            ),
        )

    def _limit_graph_updates(
        self,
        graph_updates: GraphUpdatesResponse,
        max_topics: int = 3,
        max_edges: int = 3,
    ) -> GraphUpdatesResponse:
        """Rank and cap graph updates before persistence."""
        topics = list(graph_updates.topics)
        edges = list(graph_updates.edges)
        topics = sorted(
            enumerate(topics),
            key=lambda item: (float(item[1].confidence or 0.0), -item[0]),
            reverse=True,
        )
        edges = sorted(
            enumerate(edges),
            key=lambda item: (float(item[1].confidence or 0.0), -item[0]),
            reverse=True,
        )
        ranked_topics = [topic for _, topic in topics]
        ranked_edges = [edge for _, edge in edges]
        if len(topics) > max_topics:
            logger.warning(
                f"Truncating graph topic updates for user {self.user_id} "
                f"from {len(topics)} to {max_topics}; "
                f"dropped={[topic.json_data() for topic in ranked_topics[max_topics:]]!r}"
            )
        if len(edges) > max_edges:
            logger.warning(
                f"Truncating graph edge updates for user {self.user_id} "
                f"from {len(edges)} to {max_edges}; "
                f"dropped={[edge.json_data() for edge in ranked_edges[max_edges:]]!r}"
            )
        return GraphUpdatesResponse(
            topics=ranked_topics[:max_topics],
            edges=ranked_edges[:max_edges],
        )

    def _apply_topic_updates(self, updates: list[TopicUpdateResponse]) -> tuple[list[str], list[str]]:
        """Apply accepted profile topic updates."""
        updated = []
        notes = []
        for item in updates:
            raw_topic_id = normalize_identifier(item.topic_id)
            topic_id = self.sql_db.resolve_topic_id(raw_topic_id)
            evidence = item.evidence
            confidence = float(item.confidence)
            if not topic_id or not evidence or confidence < 0.45:
                logger.warning(
                    f"Skipping invalid or weak profile topic update for user {self.user_id}: {item.json_data()!r}"
                )
                continue
            gate = self._evaluate_topic_update(item)
            if not gate.get("accept"):
                logger.info(
                    f"Profile update rejected for user {self.user_id}: {item.json_data()!r}; "
                    f"reason={gate.get('reason')!r}"
                )
                continue
            current = self.profile.topics.get(topic_id)
            values = {}
            for key in ("intuition", "details", "confidence"):
                proposed = float(getattr(item, key))
                previous = getattr(current, key, 0.0) if current else 0.0
                values[key] = max(0.0, min(1.0, max(previous, min(previous + 0.25, proposed))))
            if values:
                self.sql_db.upsert_topic(
                    topic_id,
                    name=topic_id.replace("_", " ").title(),
                    aliases=[raw_topic_id],
                    created_from=self.active_session_id,
                    confidence=confidence,
                )
                self.profile.update_topic(topic_id, **values)
                self.sql_db.record_mastery(
                    user_id=self.user_id,
                    topic_id=topic_id,
                    mastery=values.get("intuition", 0.0),
                    intuition=values.get("intuition"),
                    details=values.get("details"),
                    confidence=values.get("confidence"),
                    evidence=evidence,
                )
                updated.append(topic_id)
                notes.append(f"{topic_id}: {gate.get('reason') or evidence}")
            else:
                logger.warning(
                    f"Profile topic update had no mastery values for user {self.user_id}: {item.json_data()!r}"
                )
        return updated, notes

    def _evaluate_topic_update(self, update: TopicUpdateResponse) -> dict:
        """Evaluate whether a proposed profile update is durable enough."""
        result = self.run_task_json(
            self.profile_update_gate_task,
            self.conversation,
            dynamic_prompts=[
                f"Current learner profile:\n{self.profile}",
                f"Proposed profile topic update:\n{json.dumps(update.json_data(), ensure_ascii=True)}",
            ],
            default=ProfileUpdateGateResponse(reason="profile update gate was unavailable"),
            error_message=f"Failed to evaluate profile update for user {self.user_id}: {update.json_data()!r}",
        )
        return {
            "accept": bool(result.accept),
            "reason": result.reason.strip(),
        }

    def _save_memories(self, memories: list[ExtractedMemory]) -> int:
        """Persist extracted semantic memories."""
        return self.memory_store.save_session_memories(self.user_id, self.active_session_id, memories)

    def _apply_graph_updates(self, graph_updates: GraphUpdatesResponse) -> int:
        """Apply accepted topic graph updates."""
        count = 0
        allowed_relations = {"prerequisite", "related", "part_of", "application_of", "enables"}
        for topic in graph_updates.topics:
            topic_id = self.sql_db.resolve_topic_id(topic.topic_id)
            evidence = topic.evidence
            confidence = float(topic.confidence)
            if not topic_id or not evidence or confidence < 0.55:
                logger.warning(f"Skipping invalid or weak graph topic update for user {self.user_id}: {topic.json_data()!r}")
                continue
            self.sql_db.upsert_topic(
                topic_id,
                name=topic.name,
                description=topic.description,
                aliases=[topic.topic_id, topic.name],
                created_from=self.active_session_id,
                confidence=confidence,
            )
            count += 1
        for edge in graph_updates.edges:
            evidence = edge.evidence
            confidence = float(edge.confidence)
            relation_type = normalize_identifier(edge.relation_type)
            topic1 = self.sql_db.resolve_topic_id(edge.topic1)
            topic2 = self.sql_db.resolve_topic_id(edge.topic2)
            if (
                not evidence
                or confidence < 0.55
                or relation_type not in allowed_relations
                or not topic1
                or not topic2
                or topic1 == topic2
            ):
                logger.warning(f"Skipping invalid or weak graph edge update for user {self.user_id}: {edge.json_data()!r}")
                continue
            changed = self.sql_db.upsert_topic_edge(
                topic1,
                topic2,
                relation_type,
                confidence=confidence,
                evidence=evidence,
                session_id=self.active_session_id,
            )
            if changed:
                count += 1
        return count
