from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

from brains.comms.agent_base import Agent, Conversation, Task, get_control_model, get_teacher_model
from brains.comms.prompts_teacher import TEACHER_PROMPT
from brains.comms.prompts_session import (
    QUESTION_GOAL_LINK_PROMPT,
    SESSION_FINALIZATION_PROMPT,
    SYLLABUS_PROMPT,
)
from brains.comms.task_conversation import TaskConversation
from brains.data.db_sql import SQLDatabase
from brains.data.db_vector import Collection, SemanticDatabase
from brains.data.profile import Profile, normalize_identifier
from brains.goal_intake import GoalIntake
from brains.session_types import CommandResult, FinalizationReport, HELP_TEXT, SessionMode


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
        self.active_goal_id: str | None = None
        self.active_session_id: str | None = None
        self.active_topic_id: str | None = None
        self.active_syllabus_item_id: str | None = None
        self.goal_intake_flow = GoalIntake(
            agent=self.agent,
            profile=self.profile,
            create_goal=self.create_goal,
            close_active_question=self._close_active_question_session,
            reset_conversation=self._reset_conversation,
            set_mode=self._set_mode,
        )
        self.teacher_task = Task(
            "teacher",
            TEACHER_PROMPT,
            model=get_teacher_model(),
            visible_history=12,
            dynamic_after_context=True,
            temperature=0.35,
            num_predict=360,
        )
        self.syllabus_task = Task(
            "syllabus_planner",
            SYLLABUS_PROMPT,
            model=get_control_model(),
            context_format="packet",
            output_format="json",
            temperature=0.2,
            num_predict=700,
        )
        self.finalization_task = Task(
            "session_finalizer",
            SESSION_FINALIZATION_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format="json",
            temperature=0.1,
            num_predict=1000,
        )
        self.question_link_task = Task(
            "question_goal_linker",
            QUESTION_GOAL_LINK_PROMPT,
            model=get_control_model(),
            context_format="packet",
            output_format="json",
            temperature=0.0,
            num_predict=160,
        )

    @property
    def goal_intake(self) -> list[str]:
        return self.goal_intake_flow.messages

    @goal_intake.setter
    def goal_intake(self, value: list[str]):
        self.goal_intake_flow.messages = value

    @property
    def goal_intake_transcript(self) -> list[tuple[str, str]]:
        return self.goal_intake_flow.transcript

    @goal_intake_transcript.setter
    def goal_intake_transcript(self, value: list[tuple[str, str]]):
        self.goal_intake_flow.transcript = value

    @property
    def pending_goal_theme(self) -> str | None:
        return self.goal_intake_flow.pending_theme

    @pending_goal_theme.setter
    def pending_goal_theme(self, value: str | None):
        self.goal_intake_flow.pending_theme = value

    @property
    def pending_goal_adjacent(self) -> list[str]:
        return self.goal_intake_flow.pending_adjacent

    @pending_goal_adjacent.setter
    def pending_goal_adjacent(self, value: list[str]):
        self.goal_intake_flow.pending_adjacent = value

    @property
    def pending_resolved_goal(self) -> str | None:
        return self.goal_intake_flow.pending_resolved_goal

    @pending_resolved_goal.setter
    def pending_resolved_goal(self, value: str | None):
        self.goal_intake_flow.pending_resolved_goal = value

    def startup_message(self) -> str:
        goal = self.sql_db.get_recent_active_goal(self.user_id)
        lines = [f"Hi {self.user_id}. What do you want to understand today?"]
        if goal:
            lines.extend([
                "",
                f"Most recent goal: {goal['title']}",
                f"Next step: {goal.get('next_step') or 'continue from the current milestone'}",
                "Type /continue to pick it back up, /ask <question> for a one-off, or /goal <topic> to start a new path.",
            ])
        else:
            lines.append("Type /goal <topic> for a long-term path, or just ask a one-off question.")
        return "\n".join(lines)

    def _set_mode(self, mode: str):
        self.mode = mode

    def handle(self, text: str) -> CommandResult:
        text = text.strip()
        if not text:
            return CommandResult("")
        if text.startswith("/"):
            return self.handle_command(text)
        if self.mode in {"goal_intake", "goal_confirm"}:
            return CommandResult(self.goal_intake_flow.continue_intake(text, self.mode))
        if self.mode == "goal" and self.active_goal_id:
            return CommandResult(self._goal_turn(text))
        return CommandResult(self.ask(text))

    def handle_command(self, text: str) -> CommandResult:
        command, _, arg = text.partition(" ")
        command = command.lower()
        arg = arg.strip()
        match command:
            case "/goal" | "/learn":
                return CommandResult(self.goal_intake_flow.start(arg or None))
            case "/continue":
                self.goal_intake_flow.clear()
                return CommandResult(self.continue_goal())
            case "/goals":
                return CommandResult(self.render_goals())
            case "/ask":
                if not arg:
                    return CommandResult("Ask it like this: /ask what is covariance?")
                self.goal_intake_flow.clear()
                return CommandResult(self.ask(arg))
            case "/done":
                return CommandResult(self.finalize().render())
            case "/save":
                return CommandResult(f"Saved conversation to {self.save_partial()}")
            case "/profile":
                return CommandResult(self.render_profile())
            case "/topic":
                return CommandResult(self.render_topic())
            case "/new":
                path = self.save_partial(close_status="saved")
                self._reset_conversation()
                self.mode = "idle"
                self.active_goal_id = None
                self.active_session_id = None
                self.active_topic_id = None
                self.active_syllabus_item_id = None
                self.goal_intake_flow.clear()
                return CommandResult(f"Saved the previous conversation to {path}\nFresh session ready.")
            case "/help":
                return CommandResult(HELP_TEXT)
            case "/quit" | "/exit":
                path = self.save_partial(close_status="saved")
                return CommandResult(f"Saved conversation to {path}", should_quit=True)
            case _:
                return CommandResult(f"I do not know {command} yet.\n\n{HELP_TEXT}")

    def create_goal(self, target: str) -> str:
        self._close_active_question_session(status="answered")
        plan = self._generate_syllabus(target)
        title = plan["title"]
        topic_id = normalize_identifier(plan.get("target_topic") or target)
        duplicate = self._find_duplicate_goal(title, target, topic_id)
        if duplicate:
            self.active_goal_id = duplicate["id"]
            self.active_topic_id = duplicate.get("target_topic_id")
            self.mode = "goal"
            self.active_session_id = self.sql_db.create_goal_session(
                self.user_id,
                session_type="goal",
                goal_id=self.active_goal_id,
                metadata={"resumed_from_duplicate_request": target},
            )
            self._reset_conversation()
            self._apply_goal_context()
            item = self.sql_db.get_current_syllabus_item(self.active_goal_id)
            if item:
                self.active_syllabus_item_id = item["id"]
                self.sql_db.update_syllabus_item(item["id"], status="active")
            return (
                f"You already have this active goal: {duplicate['title']}\n"
                f"Picking it back up instead of creating a duplicate.\n"
                f"Current milestone: {item['title'] if item else 'open exploration'}\n"
                f"Next step: {duplicate.get('next_step') or (item.get('objective') if item else 'continue the lesson')}"
            )
        goal_id = self.sql_db.create_learning_goal(
            user_id=self.user_id,
            title=title,
            target=target,
            target_topic_id=topic_id,
            target_topic_name=plan.get("topic_name") or title,
        )
        self.sql_db.create_syllabus(goal_id, title, plan["milestones"])
        self.active_goal_id = goal_id
        self.active_topic_id = topic_id
        self.mode = "goal"
        self.active_session_id = self.sql_db.create_goal_session(
            self.user_id,
            session_type="goal",
            goal_id=goal_id,
            metadata={"target": target},
        )
        self._reset_conversation()
        self._apply_goal_context()
        first_item = self.sql_db.get_current_syllabus_item(goal_id)
        if first_item:
            self.active_syllabus_item_id = first_item["id"]
            self.sql_db.update_syllabus_item(first_item["id"], status="active")

        syllabus = self._render_syllabus(goal_id)
        first_prompt = first_item["objective"] if first_item else target
        response = self._goal_turn(f"Start this learning goal: {first_prompt}")
        return (
            f"Created learning goal: {title}\n\n"
            f"{syllabus}\n\n"
            "Starting with the first milestone.\n\n"
            f"{response}"
        )

    def _find_duplicate_goal(self, title: str, target: str, topic_id: str):
        normalized_target = normalize_identifier(target)
        normalized_title = normalize_identifier(title)
        for goal in self.sql_db.get_active_goals(self.user_id):
            if goal.get("target_topic_id") == topic_id:
                return goal
            if normalize_identifier(goal.get("target", "")) == normalized_target:
                return goal
            if normalize_identifier(goal.get("title", "")) == normalized_title:
                return goal
        return None

    def continue_goal(self) -> str:
        self._close_active_question_session(status="answered")
        goal = self.sql_db.get_recent_active_goal(self.user_id)
        if not goal:
            return "No active goals yet. Start one with /goal <topic>."
        self.active_goal_id = goal["id"]
        self.active_topic_id = goal.get("target_topic_id")
        self.mode = "goal"
        self.active_session_id = self.sql_db.create_goal_session(
            self.user_id,
            session_type="goal",
            goal_id=self.active_goal_id,
        )
        self._reset_conversation()
        self._apply_goal_context()
        item = self.sql_db.get_current_syllabus_item(self.active_goal_id)
        if item:
            self.active_syllabus_item_id = item["id"]
            self.sql_db.update_syllabus_item(item["id"], status="active")
        return (
            f"Picking up: {goal['title']}\n"
            f"Current milestone: {item['title'] if item else 'open exploration'}\n"
            f"Next step: {goal.get('next_step') or (item.get('objective') if item else 'continue the lesson')}"
        )

    def ask(self, question: str) -> str:
        if self.mode != "question" or not self.active_session_id:
            self._reset_conversation()
            self.mode = "question"
            self.active_goal_id = None
            self.active_syllabus_item_id = None
            self.active_session_id = self.sql_db.create_goal_session(
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
        self._maybe_link_question_to_goal(question)
        conversation_path = self._write_conversation()
        if self.active_session_id:
            self.sql_db.save_goal_session_progress(
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
        milestone_status = updates.get("milestone_status", "continue")
        if milestone_status not in {"done", "continue"}:
            milestone_status = "continue"

        topics_updated, topic_update_notes = self._apply_topic_updates(updates.get("topic_updates", []))
        memories_saved = self._save_memories(updates.get("memories", []))
        graph_changes = self._apply_graph_updates(updates.get("graph_updates", {}))

        if self.active_goal_id:
            self.sql_db.touch_goal(self.active_goal_id, summary=summary, next_step=next_step)
            if self.active_syllabus_item_id:
                item_status = "done" if milestone_status == "done" else "active"
                self.sql_db.update_syllabus_item(self.active_syllabus_item_id, status=item_status, summary=summary)
            self.sql_db.log_progress_event(
                self.user_id,
                event_type="session_finalized",
                content=summary,
                goal_id=self.active_goal_id,
                session_id=self.active_session_id,
                evidence=summary,
                metadata={"next_step": next_step},
            )

        if self.active_session_id:
            self.sql_db.finish_goal_session(
                self.active_session_id,
                conversation_path=conversation_path,
                summary=summary,
                next_step=next_step,
            )

        audit_id = self.sql_db.write_audit_log(
            user_id=self.user_id,
            session_id=self.active_session_id,
            goal_id=self.active_goal_id,
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
            milestone_status=milestone_status,
            memories_saved=memories_saved,
            topics_updated=topics_updated,
            topic_update_notes=topic_update_notes,
            graph_changes=graph_changes,
        )
        self._reset_conversation()
        self.mode = "idle"
        self.active_session_id = None
        self.active_goal_id = None
        self.active_syllabus_item_id = None
        self.goal_intake_flow.clear()
        return report

    def save_partial(self, close_status: str | None = None) -> str:
        path = self._write_conversation()
        if self.active_session_id and close_status:
            self.sql_db.finish_goal_session(
                self.active_session_id,
                conversation_path=path,
                status=close_status,
            )
        elif self.active_session_id:
            self.sql_db.save_goal_session_progress(self.active_session_id, path)
        return path

    def _close_active_question_session(self, status: str):
        if self.mode != "question" or not self.active_session_id:
            return
        path = self._write_conversation()
        self.sql_db.finish_goal_session(
            self.active_session_id,
            conversation_path=path,
            status=status,
        )
        self.active_session_id = None

    def _write_conversation(self) -> str:
        filename = f"{self.user_id}-{datetime.now().isoformat(timespec='seconds').replace(':', '-')}"
        self.conversation.save(filename)
        return str(Path("data/conversations") / f"{filename}.json")

    def render_goals(self) -> str:
        goals = self.sql_db.get_active_goals(self.user_id)
        if not goals:
            return "No active goals yet. Start one with /goal <topic>."
        rendered = ["Active goals:"]
        for goal in goals:
            item = self.sql_db.get_current_syllabus_item(goal["id"])
            rendered.append(
                f"- {goal['title']} [{goal['status']}]\n"
                f"  Current: {item['title'] if item else 'open exploration'}\n"
                f"  Next: {goal.get('next_step') or (item.get('objective') if item else 'continue')}"
            )
        return "\n".join(rendered)

    def render_topic(self) -> str:
        if self.active_goal_id:
            goal = self.sql_db.get_goal(self.active_goal_id)
            item = self.sql_db.get_current_syllabus_item(self.active_goal_id)
            return (
                f"Goal: {goal['title']}\n"
                f"Topic: {goal.get('target_topic_id')}\n"
                f"Current milestone: {item['title'] if item else 'open exploration'}"
            )
        if self.active_topic_id:
            return f"Current topic: {self.active_topic_id}"
        return "No active topic. Ask a question or start a goal with /goal <topic>."

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
        goal = self.sql_db.get_recent_active_goal(self.user_id)
        if goal:
            lines.append("")
            lines.append(f"Most recent active goal: {goal['title']}")
            lines.append(f"Next: {goal.get('next_step') or 'continue from the current milestone'}")
        return "\n".join(lines)

    def _goal_turn(self, text: str) -> str:
        self._apply_goal_context()
        return "\n\n".join(self._respond(text))

    def _reset_conversation(self):
        self.conversation = Conversation()
        self.teacher_context = ""

    def _respond(self, user_message: str):
        self.conversation.append_user(user_message)
        dynamic_prompts = [self.teacher_context] if self.teacher_context else []
        yield from self.stream_task(self.teacher_task, self.conversation, dynamic_prompts=dynamic_prompts)

    def _generate_syllabus(self, target: str) -> dict:
        packet = (
            f"User profile:\n{self.profile}\n\n"
            f"Requested goal:\n{target}\n\n"
            f"Related topic context:\n{self.sql_db.get_related_topics_pretty([normalize_identifier(target)])}"
        )
        try:
            plan = self.agent.run_task_json(self.syllabus_task, Conversation(), packet=packet)
        except Exception:
            plan = {}
        milestones = plan.get("milestones") if isinstance(plan, dict) else None
        if not milestones:
            topic = normalize_identifier(target)
            readable = target.strip().capitalize()
            milestones = [
                {"title": f"Orient around {readable}", "objective": f"Build an intuitive map of {target}."},
                {"title": "Core mechanism", "objective": "Understand the central moving parts and why they matter."},
                {"title": "Worked example", "objective": "Apply the idea to a concrete example."},
                {"title": "Deeper structure", "objective": "Connect the idea to adjacent concepts and edge cases."},
            ]
            plan = {"title": readable, "target_topic": topic, "milestones": milestones}
        plan["title"] = plan.get("title") or target.strip().capitalize()
        plan["target_topic"] = normalize_identifier(plan.get("target_topic") or target)
        plan["milestones"] = self._calibrate_milestones(target, milestones[:6])
        return plan

    def _calibrate_milestones(self, target: str, milestones: list[dict]) -> list[dict]:
        if not milestones:
            return milestones
        target_lower = target.lower()
        first_title = milestones[0].get("title", "").lower()
        generic_starts = ("foundations of vector", "basic vector", "vector spaces", "fundamentals of vector")
        if "attention" in target_lower and any(first_title.startswith(prefix) for prefix in generic_starts):
            return [
                {
                    "title": "Query-key similarity as geometry",
                    "objective": "See attention as comparing token vectors by direction and alignment.",
                },
                {
                    "title": "Attention weights as soft selection",
                    "objective": "Understand how similarity scores become a weighted blend of value vectors.",
                },
                {
                    "title": "Multi-head attention as multiple views",
                    "objective": "Understand how separate heads attend to different geometric relationships.",
                },
                *milestones[1:4],
            ][:6]
        if "spectral sequence" in target_lower:
            advanced_starts = ("chain complex", "understand chain", "homology", "filtered complex")
            if "from scratch" in target_lower or any(first_title.startswith(prefix) for prefix in advanced_starts):
                return [
                    {
                        "title": "Topology as flexible sameness",
                        "objective": "Build intuition for continuous deformation, holes, and why topology studies shape without rigid geometry.",
                    },
                    {
                        "title": "From shapes to algebra",
                        "objective": "See why algebraic topology translates geometric features into groups, maps, and computations.",
                    },
                    {
                        "title": "Chains, boundaries, and homology",
                        "objective": "Understand chains and boundaries as a bookkeeping system for holes.",
                    },
                    {
                        "title": "Filtrations as layered information",
                        "objective": "Understand how a complex can be revealed in stages before introducing spectral sequences.",
                    },
                    {
                        "title": "Spectral sequences as organized approximation",
                        "objective": "See pages and differentials as a disciplined way to track what survives through layers.",
                    },
                    *milestones[1:2],
                ][:6]
        return milestones

    def _render_syllabus(self, goal_id: str) -> str:
        items = self.sql_db.get_syllabus_items(goal_id)
        lines = ["Syllabus:"]
        for item in items:
            lines.append(f"{item['position']}. {item['title']} - {item.get('objective') or ''}".rstrip())
        return "\n".join(lines)

    def _apply_goal_context(self):
        if not self.active_goal_id:
            return
        goal = self.sql_db.get_goal(self.active_goal_id)
        items = self.sql_db.get_syllabus_items(self.active_goal_id)
        current = self.sql_db.get_current_syllabus_item(self.active_goal_id)
        syllabus_text = "\n".join(
            f"{item['position']}. {item['title']} [{item['status']}]: {item.get('objective') or ''}"
            for item in items
        )
        memories = self._query_memories(goal["target"])
        self.teacher_context = (
            f"User profile:\n{self.profile}\n\n"
            f"Active long-term goal:\n{goal['title']}\n"
            f"Target topic: {goal.get('target_topic_id')}\n"
            f"Current milestone: {current['title'] if current else 'open exploration'}\n"
            f"Milestone objective: {current.get('objective') if current else goal['target']}\n"
            f"Previous goal summary: {goal.get('summary') or 'none yet'}\n"
            f"Next recommended step: {goal.get('next_step') or 'start from the current milestone'}\n\n"
            f"Syllabus:\n{syllabus_text}\n\n"
            f"Relevant memories:\n{memories}"
        )

    def _build_question_context(self, question: str) -> str:
        active_goal = self.sql_db.get_recent_active_goal(self.user_id)
        goal_text = ""
        if active_goal:
            goal_text = (
                f"Potentially related active goal: {active_goal['title']}\n"
                "Do not turn this one-off question into a learning goal unless the user explicitly asks.\n"
            )
        return (
            f"User profile:\n{self.profile}\n\n"
            f"{goal_text}"
            f"Relevant memories:\n{self._query_memories(question)}\n\n"
            "Answer this as a one-off question. Keep it useful and lightweight."
        )

    def _query_memories(self, query: str) -> str:
        parts = []
        for collection in (
            Collection.INSIGHTS,
            Collection.CONFUSIONS,
            Collection.SUCCESSFUL_EXPLANATIONS,
            Collection.LEARNING_PREFERENCES,
        ):
            try:
                text = self.vector_db.query_pretty(
                    collection_name=collection,
                    query_texts=[query],
                    n_results=3,
                    user_id=self.user_id,
                )
            except Exception:
                text = ""
            if text:
                parts.append(f"{collection.value}:\n{text}")
        return "\n\n".join(parts) if parts else "none retrieved"

    def _maybe_link_question_to_goal(self, question: str):
        if not self.active_session_id:
            return
        goals = self.sql_db.get_active_goals(self.user_id)
        if not goals:
            return
        packet = {
            "question": question,
            "active_goals": [
                {
                    "goal_id": goal["id"],
                    "title": goal["title"],
                    "target": goal["target"],
                    "summary": goal.get("summary"),
                }
                for goal in goals
            ],
        }
        try:
            result = self.agent.run_task_json(
                self.question_link_task,
                Conversation(),
                packet=json.dumps(packet),
            )
        except Exception:
            result = {"link": False}
        if result.get("link") and float(result.get("confidence", 0)) >= 0.75:
            goal_id = result.get("goal_id")
            if any(goal["id"] == goal_id for goal in goals):
                self.sql_db.link_question_to_goal(
                    self.user_id,
                    self.active_session_id,
                    goal_id,
                    float(result.get("confidence", 0)),
                    result.get("evidence", "Model linked this question to the goal."),
                )

    def _finalize_updates(self) -> dict:
        try:
            result = self.run_task_json(self.finalization_task, self.conversation, visible=False)
        except Exception:
            result = {}
        if not isinstance(result, dict):
            result = {}
        visible = list(self.conversation.visible_messages())
        last_user = next((msg.content for msg in reversed(visible) if msg.role == "user"), "")
        result.setdefault("summary", f"worked on {self.active_topic_id or 'a learning question'}")
        result.setdefault("next_step", "continue from the last question")
        result.setdefault("topic_updates", [])
        result.setdefault("memories", [])
        result.setdefault("graph_updates", {"topics": [], "edges": []})
        if last_user and not result["memories"]:
            topic_id = self.active_topic_id or normalize_identifier(last_user)[:60] or "general_learning"
            result["memories"] = [
                {
                    "type": "insight",
                    "topic_id": topic_id,
                    "text": f"Recent learning thread included: {last_user}",
                    "confidence": 0.4,
                }
            ]
        return result

    def _apply_topic_updates(self, updates: list[dict]) -> tuple[list[str], list[str]]:
        updated = []
        notes = []
        for item in updates:
            topic_id = normalize_identifier(item.get("topic_id", ""))
            evidence = item.get("evidence", "")
            confidence = float(item.get("confidence", 0.0))
            if not topic_id or not evidence or confidence < 0.45:
                continue
            negative_evidence = (
                "did not demonstrate",
                "unclear",
                "confused",
                "fuzzy",
                "outside prior knowledge",
                "outside what",
            )
            if any(phrase in evidence.lower() for phrase in negative_evidence):
                continue
            positive_evidence = (
                "user correctly",
                "user demonstrated",
                "user understood",
                "user recognized",
                "user paraphrased",
                "learner correctly",
                "learner demonstrated",
                "learner understood",
                "learner recognized",
                "learner paraphrased",
            )
            if not any(phrase in evidence.lower() for phrase in positive_evidence):
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
                notes.append(f"{topic_id}: {evidence}")
        return updated, notes

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
