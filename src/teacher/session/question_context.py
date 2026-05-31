from __future__ import annotations

import json
import logging

from teacher.agent.conversation import Conversation
from teacher.persistence.vector import Collection
from teacher.session.types import QuestionPlan, QuestionTopicResolutionResponse, TopicGraphConnectionResponse
from teacher.utils.identifiers import normalize_identifier


logger = logging.getLogger(__name__)


class QuestionContextMixin:
    """Build temporary planning and retrieval context for learner questions."""

    def _build_question_context(self, question: str) -> str:
        """Build the full prompt context for a learner question."""
        plan = self._build_question_plan(question)
        if plan.target_topics:
            self.active_topic_id = plan.target_topics[0]
        return (
            f"User profile:\n{self.profile}\n\n"
            f"{plan.render()}\n\n"
            f"Relevant memories:\n{self._query_memories(question, topic_hints=plan.memory_topic_hints)}\n\n"
            f"Similar previous questions:\n{self._query_previous_asks(question)}\n\n"
            "Answer this as a focused learning conversation. Keep it useful and lightweight.\n"
            "Use the learner's own wording as the starting point, not a generic overview.\n"
            "If they propose a mental model, sharpen that model and explain the practical consequence.\n"
            "If they say they are fuzzy, answer the fuzzy distinction directly before offering advice.\n"
            "Use the question plan as temporary planning context, not as durable profile fact.\n"
            "Only mention assumptions when they are uncertain enough to affect the learning path.\n"
            "When relevant memories are retrieved, use them to continue the prior line of reasoning rather than restarting from a generic explanation.\n"
            "Avoid broad comparison lists unless the learner explicitly asks for a list."
        )

    def _build_question_plan(self, question: str) -> QuestionPlan:
        """Resolve a question into target topics and planning assumptions."""
        question_resolution = self._resolve_question(question)
        target_topics = self._place_question_topics(question_resolution["topics"])
        return self.question_planner.build(target_topics, self._profile_topic_hints(), question_resolution["intent"])

    def _resolve_question(self, question: str) -> dict:
        """Resolve a raw question into intent and candidate topics."""
        conversation = Conversation()
        conversation.append_user(question)
        known_topics = self.sql_db.get_topic_summaries(limit=40)
        result = self.run_task_json(
            self.question_topic_task,
            conversation,
            dynamic_prompts=[
                f"User profile:\n{self.profile}",
                f"Known topic graph candidates:\n{json.dumps(known_topics, ensure_ascii=True)}",
            ],
            default=QuestionTopicResolutionResponse(),
            error_message=f"Failed to resolve question topics for user {self.user_id}",
        )
        topics = []
        for item in result.topics:
            topic_id = normalize_identifier(item.topic_id)
            if not topic_id:
                continue
            topics.append(
                {
                    "topic_id": self.sql_db.resolve_topic_id(topic_id),
                    "name": item.name or topic_id.replace("_", " ").title(),
                    "description": item.description or "",
                    "confidence": float(item.confidence),
                }
            )
        return {"intent": result.intent, "topics": topics[:3]}

    def _query_memories(self, query: str, topic_hints: list[str] | None = None) -> str:
        """Retrieve semantic memories for the current question."""
        parts = []
        queries = self._memory_queries(query, topic_hints)
        for collection in (
            Collection.INSIGHTS,
            Collection.CONFUSIONS,
            Collection.PARTIAL_UNDERSTANDINGS,
            Collection.SUCCESSFUL_EXPLANATIONS,
            Collection.LEARNING_PREFERENCES,
        ):
            try:
                text = self.vector_db.query_pretty(
                    collection_name=collection,
                    query_texts=queries,
                    n_results=3,
                    user_id=self.user_id,
                )
            except Exception:
                logger.exception(
                    f"Failed to query semantic memory collection {collection.value} for user {self.user_id}"
                )
                text = ""
            if text:
                parts.append(f"{collection.value}:\n{text}")
        return "\n\n".join(parts) if parts else "none retrieved"

    def _query_previous_asks(self, query: str) -> str:
        """Retrieve prior similar questions for the current user."""
        try:
            asks = self.vector_db.find_asks(query, user_id=self.user_id)
        except Exception:
            logger.exception(f"Failed to query previous asks for user {self.user_id}")
            return "none retrieved"
        deduped = []
        for ask in asks:
            text = ask.strip()
            if text and text != query and text not in deduped:
                deduped.append(text)
        return "\n".join(f"- {ask}" for ask in deduped[:3]) if deduped else "none retrieved"

    def _profile_topic_hints(self) -> list[str]:
        """Return the strongest profile topics as graph search hints."""
        return [
            topic_id
            for topic_id, state in sorted(
                self.profile.topics.items(),
                key=lambda item: (item[1].confidence, item[1].intuition, item[1].details),
                reverse=True,
            )[:5]
        ]

    def _place_question_topics(self, topics: list[dict]) -> list[str]:
        """Place resolved question topics in the topic graph."""
        placed = []
        candidates = self.sql_db.get_topic_summaries(limit=60)
        for topic in topics:
            topic_id = normalize_identifier(topic.get("topic_id", ""))
            if not topic_id:
                continue
            resolved = self.sql_db.resolve_topic_id(topic_id)
            if self.sql_db.topic_exists(resolved):
                placed.append(resolved)
                continue
            connections = self._evaluate_topic_connections(topic, candidates)
            same_as = self._best_same_as(connections)
            if same_as:
                placed.append(same_as)
                continue
            strong_connections = [
                connection
                for connection in connections
                if normalize_identifier(connection.get("relation_type", "")) in {
                    "prerequisite",
                    "related",
                    "part_of",
                    "application_of",
                    "enables",
                }
                and float(connection.get("confidence", 0.0)) >= 0.65
                and self.sql_db.resolve_topic_id(connection.get("topic_id", ""))
                and self.sql_db.resolve_topic_id(connection.get("topic_id", "")) != resolved
            ]
            if not strong_connections:
                if float(topic.get("confidence", 0.0)) >= 0.65:
                    self.sql_db.upsert_topic(
                        resolved,
                        name=topic.get("name"),
                        description=topic.get("description"),
                        confidence=float(topic.get("confidence", 0.65)),
                    )
                placed.append(resolved)
                continue
            self.sql_db.upsert_topic(
                resolved,
                name=topic.get("name"),
                description=topic.get("description"),
                confidence=0.45,
            )
            placed.append(resolved)
            for connection in strong_connections:
                relation = normalize_identifier(connection.get("relation_type", ""))
                confidence = float(connection.get("confidence", 0.0))
                target = self.sql_db.resolve_topic_id(connection.get("topic_id", ""))
                self.sql_db.upsert_topic_edge(
                    resolved,
                    target,
                    relation,
                    confidence=confidence,
                    evidence=connection.get("evidence"),
                    session_id=self.active_session_id,
                )
        return placed

    def _evaluate_topic_connections(self, topic: dict, candidates: list[dict]) -> list[dict]:
        """Ask the model how a new topic connects to the existing graph."""
        if not candidates:
            return []
        conversation = Conversation()
        conversation.append_user(f"New/resolved topic:\n{json.dumps(topic, ensure_ascii=True)}")
        result = self.run_task_json(
            self.topic_connection_task,
            conversation,
            dynamic_prompts=[f"Candidate existing graph topics:\n{json.dumps(candidates, ensure_ascii=True)}"],
            default=TopicGraphConnectionResponse(),
            error_message=f"Failed to evaluate topic graph connections for user {self.user_id} and topic {topic!r}",
        )
        allowed_topics = {candidate["topic_id"] for candidate in candidates}
        connections = []
        for connection in result.connections:
            topic_id = self.sql_db.resolve_topic_id(connection.topic_id)
            if topic_id not in allowed_topics:
                continue
            connections.append({**connection.json_data(), "topic_id": topic_id})
        return connections

    @staticmethod
    def _best_same_as(connections: list[dict]) -> str | None:
        """Return the strongest same-as graph match."""
        same_as = [
            connection
            for connection in connections
            if normalize_identifier(connection.get("relation_type", "")) == "same_as"
            and float(connection.get("confidence", 0.0)) >= 0.85
        ]
        if not same_as:
            return None
        return max(same_as, key=lambda item: float(item.get("confidence", 0.0)))["topic_id"]

    @staticmethod
    def _memory_queries(query: str, topic_hints: list[str] | None = None) -> list[str]:
        """Build memory search queries from a question and topic hints."""
        queries = [query]
        for topic_id in topic_hints or []:
            readable = topic_id.replace("_", " ").strip()
            if readable:
                queries.append(f"{query}\nRelated learner topic: {readable}")
                queries.append(readable)
        deduped = []
        for item in queries:
            if item and item not in deduped:
                deduped.append(item)
        return deduped[:8]
