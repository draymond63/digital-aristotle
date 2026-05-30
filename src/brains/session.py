from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import logging

from brains.comms.agent_base import Agent, Conversation, Task, get_control_model, get_teacher_model
from brains.comms.prompts_teacher import TEACHER_PROMPT
from brains.comms.prompts_session import (
    PROFILE_UPDATE_GATE_PROMPT,
    QUESTION_TOPIC_RESOLUTION_PROMPT,
    SESSION_GRAPH_UPDATES_PROMPT,
    SESSION_MEMORY_EXTRACTION_PROMPT,
    SESSION_SUMMARY_PROMPT,
    SESSION_TOPIC_UPDATES_PROMPT,
    TOPIC_GRAPH_CONNECTION_PROMPT,
)
from brains.comms.task_conversation import TaskConversation
from brains.data.db_sql import SQLDatabase
from brains.data.db_vector import Collection, SemanticDatabase
from brains.data.profile import Profile, normalize_identifier
from brains.session_types import (
    CommandResult,
    FinalizationReport,
    HELP_TEXT,
    GraphUpdatesResponse,
    MemoryUpdateResponse,
    ProfileUpdateGateResponse,
    SessionGraphUpdatesResponse,
    QuestionTopicResolutionResponse,
    SessionFinalizationResponse,
    SessionMemoryExtractionResponse,
    SessionMode,
    SessionSummaryResponse,
    SessionTopicUpdatesResponse,
    TopicUpdateResponse,
    TopicGraphConnectionResponse,
)


logger = logging.getLogger(__name__)


class LearningSession(TaskConversation):
    def __init__(
        self,
        user_id: str = "daniel",
        sql_db: SQLDatabase | None = None,
        vector_db: SemanticDatabase | None = None,
        profile: Profile | None = None,
        agent: Agent | None = None,
    ):
        super().__init__(agent=agent)
        self.user_id = normalize_identifier(user_id) or "default_user"
        self.sql_db = sql_db or SQLDatabase()
        self.vector_db = vector_db or SemanticDatabase()
        self.profile = profile or Profile.load_user(self.user_id)
        self.teacher_context = ""
        self.sql_db.abandon_active_question_sessions(self.user_id)
        self.mode: SessionMode = "idle"
        self.active_session_id: str | None = None
        self.active_topic_id: str | None = None
        self.teacher_task = Task(
            "teacher",
            TEACHER_PROMPT,
            model=get_teacher_model(),
            visible_history=12,
            dynamic_after_context=True,
            temperature=0.35,
            num_predict=360,
        )
        self.summary_task = Task(
            "session_summary",
            SESSION_SUMMARY_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format=SessionSummaryResponse,
            temperature=0.1,
            num_predict=300,
        )
        self.topic_updates_task = Task(
            "session_topic_updates",
            SESSION_TOPIC_UPDATES_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format=SessionTopicUpdatesResponse,
            temperature=0.1,
            num_predict=700,
        )
        self.memory_extraction_task = Task(
            "session_memory_extraction",
            SESSION_MEMORY_EXTRACTION_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format=SessionMemoryExtractionResponse,
            temperature=0.1,
            num_predict=700,
        )
        self.graph_updates_task = Task(
            "session_graph_updates",
            SESSION_GRAPH_UPDATES_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format=SessionGraphUpdatesResponse,
            temperature=0.1,
            num_predict=900,
        )
        self.profile_update_gate_task = Task(
            "profile_update_gate",
            PROFILE_UPDATE_GATE_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format=ProfileUpdateGateResponse,
            temperature=0.0,
            num_predict=180,
        )
        self.question_topic_task = Task(
            "question_topic_resolver",
            QUESTION_TOPIC_RESOLUTION_PROMPT,
            model=get_control_model(),
            output_format=QuestionTopicResolutionResponse,
            temperature=0.0,
            num_predict=350,
        )
        self.topic_connection_task = Task(
            "topic_graph_connection",
            TOPIC_GRAPH_CONNECTION_PROMPT,
            model=get_control_model(),
            output_format=TopicGraphConnectionResponse,
            temperature=0.0,
            num_predict=450,
        )

    def startup_message(self) -> str:
        return f"Hi {self.user_id}. What do you want to understand today?"

    def handle(self, text: str) -> CommandResult:
        text = text.strip()
        if not text:
            return CommandResult("")
        if text.startswith("/"):
            return self.handle_command(text)
        return CommandResult(self.ask(text))

    def handle_command(self, text: str) -> CommandResult:
        command, _, arg = text.partition(" ")
        command = command.lower()
        arg = arg.strip()
        match command:
            case "/ask":
                if not arg:
                    return CommandResult("Ask it like this: /ask what is covariance?")
                if self.mode == "question" and self.active_session_id:
                    report = self.finalize().render()
                    response = self.ask(arg)
                    return CommandResult(f"{report}\n\nNew question:\n{response}")
                return CommandResult(self.ask(arg))
            case "/done":
                return CommandResult(self.finalize().render())
            case "//save":
                return CommandResult(f"Saved conversation to {self.save_partial()}")
            case "//profile":
                return CommandResult(self.render_profile())
            case "//topic":
                return CommandResult(self.render_topic())
            case "//help":
                return CommandResult(HELP_TEXT)
            case "//quit" | "//exit":
                path = self.save_partial(close_status="saved")
                return CommandResult(f"Saved conversation to {path}", should_quit=True)
            case _:
                return CommandResult(f"I do not know {command} yet.\n\n{HELP_TEXT}")

    def ask(self, question: str) -> str:
        if self.mode != "question" or not self.active_session_id:
            self._reset_conversation()
            self.mode = "question"
            self.active_session_id = self.sql_db.create_learning_session(
                self.user_id,
                session_type="question",
                metadata={"question": question},
            )
        context = self._build_question_context(question)
        self.teacher_context = context
        self.vector_db.log_ask(
            question,
            session_id=abs(hash(self.active_session_id)) % (10**12),
            user_id=self.user_id,
        )
        response = "\n\n".join(self._respond(question))
        conversation_path = self._write_conversation()
        if self.active_session_id:
            self.sql_db.save_learning_session_progress(
                self.active_session_id,
                conversation_path=conversation_path,
            )
        return response

    def finalize(self) -> FinalizationReport:
        conversation_path = self._write_conversation()
        backup_path = str(self.profile.backup())
        updates = self._finalize_updates()
        summary = updates.summary or "we made progress on the current question"
        next_step = updates.next_step or "continue from the last useful question"

        topics_updated, topic_update_notes = self._apply_topic_updates(updates.topic_updates)
        memories_saved = self._save_memories(updates.memories)
        graph_changes = self._apply_graph_updates(updates.graph_updates)

        if self.active_session_id:
            self.sql_db.finish_learning_session(
                self.active_session_id,
                conversation_path=conversation_path,
                summary=summary,
                next_step=next_step,
            )

        audit_id = self.sql_db.write_audit_log(
            user_id=self.user_id,
            session_id=self.active_session_id,
            profile_backup_path=backup_path,
            conversation_path=conversation_path,
            summary=summary,
            changes=updates.json_data(),
        )
        report = FinalizationReport(
            summary=summary,
            next_step=next_step,
            conversation_path=conversation_path,
            profile_backup_path=backup_path,
            audit_id=audit_id,
            memories_saved=memories_saved,
            topics_updated=topics_updated,
            topic_update_notes=topic_update_notes,
            graph_changes=graph_changes,
        )
        self._reset_conversation()
        self.mode = "idle"
        self.active_session_id = None
        self.active_topic_id = None
        return report

    def save_partial(self, close_status: str | None = None) -> str:
        path = self._write_conversation()
        if self.active_session_id and close_status:
            self.sql_db.finish_learning_session(
                self.active_session_id,
                conversation_path=path,
                status=close_status,
            )
        elif self.active_session_id:
            self.sql_db.save_learning_session_progress(self.active_session_id, path)
        return path

    def _write_conversation(self) -> str:
        filename = f"{self.user_id}-{datetime.now().isoformat(timespec='seconds').replace(':', '-')}"
        self.conversation.save(filename)
        return str(Path("data/conversations") / f"{filename}.json")

    def render_topic(self) -> str:
        if self.active_topic_id:
            return f"Current topic: {self.active_topic_id}"
        return "No active topic yet. Ask a question first."

    def render_profile(self) -> str:
        lines = [f"Profile for {self.user_id}"]
        if self.profile.topics:
            lines.append("")
            lines.append("Learning frontier:")
            ranked = sorted(
                self.profile.topics.items(),
                key=lambda item: (item[1].confidence, item[1].intuition, item[1].details),
                reverse=True,
            )
            for topic_id, state in ranked[:8]:
                readable = topic_id.replace("_", " ")
                lines.append(
                    f"- {readable}: intuition {state.intuition:.2f}, "
                    f"details {state.details:.2f}, confidence {state.confidence:.2f}"
                )
        else:
            lines.append("")
            lines.append("Learning frontier: no durable topic evidence yet.")

        if self.profile.preferences:
            lines.append("")
            lines.append("Preferences:")
            for category, items in self.profile.preferences.items():
                readable_items = ", ".join(item.replace("_", " ") for item in items)
                lines.append(f"- {category.replace('_', ' ')}: {readable_items}")
        if self.profile.interests:
            lines.append("")
            lines.append("Interests: " + ", ".join(item.replace("_", " ") for item in self.profile.interests))
        return "\n".join(lines)

    def _reset_conversation(self):
        self.conversation = Conversation()
        self.teacher_context = ""

    def _respond(self, user_message: str):
        self.conversation.append_user(user_message)
        dynamic_prompts = [self.teacher_context] if self.teacher_context else []
        yield from self.stream_task(self.teacher_task, self.conversation, dynamic_prompts=dynamic_prompts)

    def _build_question_context(self, question: str) -> str:
        return (
            f"User profile:\n{self.profile}\n\n"
            f"Relevant memories:\n{self._query_memories(question, topic_hints=self._graph_connected_profile_topic_hints(question))}\n\n"
            "Answer this as a focused learning conversation. Keep it useful and lightweight.\n"
            "Use the learner's own wording as the starting point, not a generic overview.\n"
            "If they propose a mental model, sharpen that model and explain the practical consequence.\n"
            "If they say they are fuzzy, answer the fuzzy distinction directly before offering advice.\n"
            "When relevant memories are retrieved, use them to continue the prior line of reasoning rather than restarting from a generic explanation.\n"
            "Avoid broad comparison lists unless the learner explicitly asks for a list."
        )

    def _query_memories(self, query: str, topic_hints: list[str] | None = None) -> str:
        parts = []
        queries = self._memory_queries(query, topic_hints)
        for collection in (
            Collection.INSIGHTS,
            Collection.CONFUSIONS,
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

    def _profile_topic_hints(self) -> list[str]:
        return [
            topic_id
            for topic_id, state in sorted(
                self.profile.topics.items(),
                key=lambda item: (item[1].confidence, item[1].intuition, item[1].details),
                reverse=True,
            )[:5]
        ]

    def _graph_connected_profile_topic_hints(self, question: str) -> list[str]:
        profile_topics = self._profile_topic_hints()
        if not profile_topics:
            return []
        question_topics = self._resolve_question_topics(question)
        if not question_topics:
            return []
        placed_topics = self._place_question_topics(question_topics)
        return self.sql_db.connected_targets(placed_topics, profile_topics, max_hops=2)

    def _resolve_question_topics(self, question: str) -> list[str]:
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
        return topics[:3]

    def _place_question_topics(self, topics: list[dict]) -> list[str]:
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

    def _finalize_updates(self) -> SessionFinalizationResponse:
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
            memories=memories_result.memories,
            graph_updates=self._limit_graph_updates(graph_updates_result.graph_updates),
        )

    def _limit_graph_updates(
        self,
        graph_updates: GraphUpdatesResponse,
        max_topics: int = 3,
        max_edges: int = 3,
    ) -> GraphUpdatesResponse:
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
                self.sql_db.cursor.execute(
                    """
                    INSERT INTO mastery_history
                        (user_id, topic_id, mastery, timestamp, intuition, details, confidence, evidence)
                    VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?)
                    """,
                    (
                        self.user_id,
                        topic_id,
                        values.get("intuition", 0.0),
                        values.get("intuition"),
                        values.get("details"),
                        values.get("confidence"),
                        evidence,
                    ),
                )
                self.sql_db.conn.commit()
                updated.append(topic_id)
                notes.append(f"{topic_id}: {gate.get('reason') or evidence}")
            else:
                logger.warning(
                    f"Profile topic update had no mastery values for user {self.user_id}: {item.json_data()!r}"
                )
        return updated, notes

    def _evaluate_topic_update(self, update: TopicUpdateResponse) -> dict:
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

    def _save_memories(self, memories: list[MemoryUpdateResponse]) -> int:
        saved = 0
        for memory in memories:
            text = memory.text.strip()
            if not text or float(memory.confidence) < 0.35:
                logger.warning(f"Skipping invalid or weak memory for user {self.user_id}: {memory.json_data()!r}")
                continue
            memory_type = memory.type
            if memory_type not in {"insight", "confusion", "successful_explanation", "learning_preference"}:
                logger.warning(f"Skipping memory with unknown type for user {self.user_id}: {memory.json_data()!r}")
                continue
            collection = {
                "confusion": Collection.CONFUSIONS,
                "successful_explanation": Collection.SUCCESSFUL_EXPLANATIONS,
                "learning_preference": Collection.LEARNING_PREFERENCES,
            }.get(memory_type, Collection.INSIGHTS)
            memory_id = f"{self.active_session_id or 'session'}-{saved}"
            try:
                self.vector_db.add(
                    collection,
                    ids=[memory_id],
                    documents=[text],
                    metadatas=[
                        {
                            "user_id": self.user_id,
                            "session_id": self.active_session_id or "",
                            "topic_id": normalize_identifier(memory.topic_id),
                            "memory_type": memory_type,
                        }
                    ],
                )
                saved += 1
            except Exception:
                logger.exception(
                    f"Failed to save memory for user {self.user_id} "
                    f"in collection {collection.value}: {memory.json_data()!r}"
                )
                continue
        return saved

    def _apply_graph_updates(self, graph_updates: GraphUpdatesResponse) -> int:
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
