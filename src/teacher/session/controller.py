from __future__ import annotations

from datetime import datetime
from pathlib import Path

from teacher.agent.conversation import Conversation
from teacher.agent.providers import Agent, get_control_model, get_teacher_model
from teacher.agent.task_conversation import TaskConversation
from teacher.agent.types import Task
from teacher.persistence.memory_store import SemanticMemoryStore
from teacher.persistence.profile import Profile
from teacher.persistence.sql import SQLDatabase
from teacher.persistence.vector import SemanticDatabase
from teacher.session.finalizer import SessionFinalizerMixin
from teacher.session.prompts import (
    PROFILE_UPDATE_GATE_PROMPT,
    QUESTION_TOPIC_RESOLUTION_PROMPT,
    SESSION_GRAPH_UPDATES_PROMPT,
    SESSION_MEMORY_EXTRACTION_PROMPT,
    SESSION_SUMMARY_PROMPT,
    SESSION_TOPIC_UPDATES_PROMPT,
    TOPIC_GRAPH_CONNECTION_PROMPT,
)
from teacher.session.question_context import QuestionContextMixin
from teacher.session.types import (
    CommandResult,
    FinalizationReport,
    HELP_TEXT,
    ProfileUpdateGateResponse,
    SessionGraphUpdatesResponse,
    SessionMemoryExtractionResponse,
    SessionMode,
    SessionSummaryResponse,
    SessionTopicUpdatesResponse,
    QuestionTopicResolutionResponse,
    TopicGraphConnectionResponse,
)
from teacher.teaching.prompts import TEACHER_PROMPT
from teacher.teaching.question_planner import QuestionPlanner
from teacher.utils.identifiers import normalize_identifier


class LearningSession(QuestionContextMixin, SessionFinalizerMixin, TaskConversation):
    """Coordinate command handling and active learning session lifecycle."""

    def __init__(
        self,
        user_id: str = "daniel",
        sql_db: SQLDatabase | None = None,
        vector_db: SemanticDatabase | None = None,
        profile: Profile | None = None,
        agent: Agent | None = None,
        abandon_active: bool = True,
    ):
        """Initialize dependencies and task contracts for one learner."""
        super().__init__(agent=agent)
        self.user_id = normalize_identifier(user_id) or "default_user"
        self.sql_db = sql_db or SQLDatabase()
        self.vector_db = vector_db or SemanticDatabase()
        self.memory_store = SemanticMemoryStore(self.sql_db, self.vector_db)
        self.profile = profile or Profile.load_user(self.user_id)
        self.question_planner = QuestionPlanner(self.sql_db, self.profile)
        self.teacher_context = ""
        if abandon_active:
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
            num_predict=2000,
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
            visible_history=6,
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
        """Return the initial prompt for a learner."""
        return f"Hi {self.user_id}. What do you want to understand today?"

    def handle(self, text: str) -> CommandResult:
        """Route raw user text to commands or question handling."""
        text = text.strip()
        if not text:
            return CommandResult("")
        if text.startswith("/"):
            return self.handle_command(text)
        return CommandResult(self.ask(text))

    def handle_command(self, text: str) -> CommandResult:
        """Handle one slash command."""
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
        """Answer a learner question inside the active question session."""
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
        """Finalize the active session and persist durable updates."""
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
        """Persist the current conversation without finalization."""
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
        """Write the active conversation to the runtime data directory."""
        filename = f"{self.user_id}-{datetime.now().isoformat(timespec='seconds').replace(':', '-')}"
        self.conversation.save(filename)
        return str(Path("data/conversations") / f"{filename}.json")

    def render_topic(self) -> str:
        """Render the current active topic."""
        if self.active_topic_id:
            return f"Current topic: {self.active_topic_id}"
        return "No active topic yet. Ask a question first."

    def render_profile(self) -> str:
        """Render the compact learner profile."""
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
        """Reset conversation state for a new question session."""
        self.conversation = Conversation()
        self.teacher_context = ""

    def _respond(self, user_message: str):
        """Stream the teacher response for a user message."""
        self.conversation.append_user(user_message)
        dynamic_prompts = [self.teacher_context] if self.teacher_context else []
        yield from self.stream_task(self.teacher_task, self.conversation, dynamic_prompts=dynamic_prompts)

