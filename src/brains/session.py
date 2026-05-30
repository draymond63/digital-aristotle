from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

from brains.comms.agent_base import Agent, Conversation, Task, get_control_model, get_teacher_model
from brains.comms.prompts_teacher import TEACHER_PROMPT
from brains.comms.prompts_session import (
    PROFILE_UPDATE_GATE_PROMPT,
    QUESTION_TOPIC_RESOLUTION_PROMPT,
    SESSION_FINALIZATION_PROMPT,
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
    MemoryUpdateResponse,
    ProfileUpdateGateResponse,
    QuestionTopicResolutionResponse,
    SessionFinalizationResponse,
    SessionMode,
    TopicGraphConnectionResponse,
)


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
        self.finalization_task = Task(
            "session_finalizer",
            SESSION_FINALIZATION_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format=SessionFinalizationResponse,
            temperature=0.1,
            num_predict=1000,
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
                return CommandResult(self.ask(arg))
            case "/done":
                return CommandResult(self.finalize().render())
            case "//save":
                return CommandResult(f"Saved conversation to {self.save_partial()}")
            case "//profile":
                return CommandResult(self.render_profile())
            case "//topic":
                return CommandResult(self.render_topic())
            case "//new":
                path = self.save_partial(close_status="saved")
                self._reset_conversation()
                self.mode = "idle"
                self.active_session_id = None
                self.active_topic_id = None
                return CommandResult(f"Saved the previous conversation to {path}\nFresh session ready.")
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
        summary = updates.get("summary") or "we made progress on the current question"
        next_step = updates.get("next_step") or "continue from the last useful question"

        topics_updated, topic_update_notes = self._apply_topic_updates(updates.get("topic_updates", []))
        memories_saved = self._save_memories(updates.get("memories", []))
        graph_changes = self._apply_graph_updates(updates.get("graph_updates", {}))

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
            changes=updates,
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
        try:
            result = self.agent.run_task_json(
                self.question_topic_task,
                conversation,
                dynamic_prompts=[
                    f"User profile:\n{self.profile}",
                    f"Known topic graph candidates:\n{json.dumps(known_topics, ensure_ascii=True)}",
                ],
            )
        except Exception:
            return []
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
        try:
            result = self.agent.run_task_json(
                self.topic_connection_task,
                conversation,
                dynamic_prompts=[f"Candidate existing graph topics:\n{json.dumps(candidates, ensure_ascii=True)}"],
            )
        except Exception:
            return []
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

    def _finalize_updates(self) -> dict:
        try:
            result = self.run_task_json(self.finalization_task, self.conversation, visible=False)
        except Exception:
            result = SessionFinalizationResponse()
        visible = list(self.conversation.visible_messages())
        last_user = next((msg.content for msg in reversed(visible) if msg.role == "user"), "")
        result.summary = result.summary or f"worked on {self.active_topic_id or 'a learning question'}"
        result.next_step = result.next_step or "continue from the last question"
        if last_user and not result.memories:
            topic_id = self.active_topic_id or normalize_identifier(last_user)[:60] or "general_learning"
            result.memories = [
                MemoryUpdateResponse(
                    type="insight",
                    topic_id=topic_id,
                    text=f"Recent learning thread included: {last_user}",
                    confidence=0.4,
                )
            ]
        return result.json_data()

    def _apply_topic_updates(self, updates: list[dict]) -> tuple[list[str], list[str]]:
        updated = []
        notes = []
        for item in updates:
            topic_id = normalize_identifier(item.get("topic_id", ""))
            evidence = item.get("evidence", "")
            confidence = float(item.get("confidence", 0.0))
            if not topic_id or not evidence or confidence < 0.45:
                continue
            gate = self._evaluate_topic_update(item)
            if not gate.get("accept"):
                continue
            current = self.profile.topics.get(topic_id)
            values = {}
            for key in ("intuition", "details", "confidence"):
                if key in item:
                    proposed = float(item[key])
                    previous = getattr(current, key, 0.0) if current else 0.0
                    values[key] = max(0.0, min(1.0, max(previous, min(previous + 0.25, proposed))))
            if values:
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
        return updated, notes

    def _evaluate_topic_update(self, update: dict) -> dict:
        try:
            result = self.agent.run_task_json(
                self.profile_update_gate_task,
                self.conversation,
                dynamic_prompts=[
                    f"Current learner profile:\n{self.profile}",
                    f"Proposed profile topic update:\n{json.dumps(update, ensure_ascii=True)}",
                ],
            )
        except Exception:
            return {"accept": False, "reason": "profile update gate was unavailable"}
        return {
            "accept": bool(result.accept),
            "reason": result.reason.strip(),
        }

    def _save_memories(self, memories: list[dict]) -> int:
        saved = 0
        for memory in memories:
            text = memory.get("text", "").strip()
            if not text or float(memory.get("confidence", 0.0)) < 0.35:
                continue
            memory_type = memory.get("type", "insight")
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
                            "topic_id": normalize_identifier(memory.get("topic_id", "")),
                            "memory_type": memory_type,
                        }
                    ],
                )
                saved += 1
            except Exception:
                continue
        return saved

    def _apply_graph_updates(self, graph_updates: dict) -> int:
        count = 0
        allowed_relations = {"prerequisite", "related", "part_of", "application_of", "enables"}
        for topic in graph_updates.get("topics", []) or []:
            topic_id = self.sql_db.resolve_topic_id(topic.get("topic_id", ""))
            evidence = topic.get("evidence", "")
            confidence = float(topic.get("confidence", 0.0))
            if not topic_id or not evidence or confidence < 0.55:
                continue
            self.sql_db.upsert_topic(
                topic_id,
                name=topic.get("name"),
                description=topic.get("description"),
                aliases=[topic.get("topic_id", ""), topic.get("name", "")],
                created_from=self.active_session_id,
                confidence=confidence,
            )
            count += 1
        for edge in graph_updates.get("edges", []) or []:
            evidence = edge.get("evidence", "")
            confidence = float(edge.get("confidence", 0.0))
            relation_type = normalize_identifier(edge.get("relation_type", "related"))
            topic1 = self.sql_db.resolve_topic_id(edge.get("topic1", ""))
            topic2 = self.sql_db.resolve_topic_id(edge.get("topic2", ""))
            if (
                not evidence
                or confidence < 0.55
                or relation_type not in allowed_relations
                or not topic1
                or not topic2
                or topic1 == topic2
            ):
                continue
            changed = self.sql_db.upsert_topic_edge(
                topic1,
                topic2,
                relation_type,
                confidence=float(edge.get("confidence", 0.5)),
                evidence=evidence,
                session_id=self.active_session_id,
            )
            if changed:
                count += 1
        return count
