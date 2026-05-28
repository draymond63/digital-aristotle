from __future__ import annotations

from collections.abc import Callable

from brains.comms.agent_base import Agent, Conversation, Task, get_control_model
from brains.comms.prompts_session import GOAL_INTAKE_PROMPT
from brains.data.profile import Profile, normalize_identifier


class GoalIntake:
    def __init__(
        self,
        agent: Agent,
        profile: Profile,
        create_goal: Callable[[str], str],
        close_active_question: Callable[[str], None],
        reset_conversation: Callable[[], None],
        set_mode: Callable[[str], None],
    ):
        self.agent = agent
        self.profile = profile
        self.create_goal = create_goal
        self.close_active_question = close_active_question
        self.reset_conversation = reset_conversation
        self.set_mode = set_mode
        self.messages: list[str] = []
        self.transcript: list[tuple[str, str]] = []
        self.pending_theme: str | None = None
        self.pending_adjacent: list[str] = []
        self.pending_resolved_goal: str | None = None
        self.task = Task(
            "goal_intake",
            GOAL_INTAKE_PROMPT,
            model=get_control_model(),
            context_format="packet",
            output_format="json",
            temperature=0.1,
            num_predict=220,
        )

    def clear(self):
        self.messages = []
        self.transcript = []
        self.pending_theme = None
        self.pending_adjacent = []
        self.pending_resolved_goal = None

    def start(self, initial_text: str | None = None) -> str:
        self.close_active_question("answered")
        self.reset_conversation()
        self.set_mode("goal_intake")
        self.clear()
        if not initial_text:
            return (
                "What do you want to learn?\n"
                "A rough answer is fine. I will help sharpen it before making a goal."
            )
        return self.continue_intake(initial_text, mode="goal_intake")

    def continue_intake(self, text: str, mode: str) -> str:
        if mode == "goal_confirm":
            if self._is_confirmation(text):
                resolved_goal = self.pending_resolved_goal or self._fallback_resolved_goal()
                self.clear()
                prefix = f"Great. I will make this the track: {resolved_goal}\n\n"
                return prefix + self.create_goal(resolved_goal)
            self.pending_resolved_goal = None
            self.set_mode("goal_intake")

        self.messages.append(text.strip())
        self.transcript.append(("user", text.strip()))
        decision = self._evaluate()
        if len(self.messages) == 1:
            question = self._format_theme_clarification(decision)
            self.transcript.append(("assistant", question))
            return question
        if decision.get("status") == "ready" and decision.get("resolved_goal"):
            resolved_goal = self._clean_resolved_goal(decision["resolved_goal"])
            if not self._valid_resolved_goal(resolved_goal):
                resolved_goal = self._fallback_resolved_goal()
            resolved_goal = self._include_confirmed_adjacent_concepts(resolved_goal)
            self.pending_resolved_goal = resolved_goal
            self.set_mode("goal_confirm")
            return (
                f"Here is the goal I would create:\n"
                f"{resolved_goal}\n\n"
                "Reply yes to create it, or tell me what to change."
            )
        question = decision.get("question") or self._fallback_clarification()
        self.transcript.append(("assistant", question.strip()))
        return question.strip()

    def _evaluate(self) -> dict:
        transcript = "\n".join(f"{role.capitalize()}: {message}" for role, message in self.transcript)
        packet = f"User profile:\n{self.profile}\n\nGoal-intake conversation:\n{transcript}"
        try:
            decision = self.agent.run_task_json(self.task, Conversation(), packet=packet)
        except Exception:
            decision = {}
        if not isinstance(decision, dict):
            return {"status": "clarify", "question": self._fallback_clarification(), "resolved_goal": ""}
        if len(self.messages) < 2:
            return {
                "status": "clarify",
                "question": decision.get("question") or self._fallback_clarification(),
                "resolved_goal": "",
                "candidate_theme": decision.get("candidate_theme") or "",
                "adjacent_concepts": decision.get("adjacent_concepts") or [],
                "rationale": "Goal creation requires at least one clarification turn.",
            }
        if len(self.messages) >= 2 and decision.get("status") != "ready":
            return {
                "status": "ready",
                "resolved_goal": self._fallback_resolved_goal(),
                "question": "",
                "rationale": "Resolved after clarification turn.",
            }
        return decision

    @staticmethod
    def _fallback_clarification() -> str:
        return (
            "I hear a cluster of examples, but not quite the center yet. "
            "What central theme or capability are you hoping this turns into?"
        )

    def _fallback_resolved_goal(self) -> str:
        if self.pending_theme:
            adjacent = self._format_adjacent(self.pending_adjacent)
            if adjacent:
                return f"build understanding of {self.pending_theme}, including {adjacent}"
            return f"build understanding of {self.pending_theme}"
        return self._clean_resolved_goal(" ".join(self.messages).strip())

    def _include_confirmed_adjacent_concepts(self, goal: str) -> str:
        if not self.pending_adjacent:
            return goal
        latest = normalize_identifier(self.messages[-1]) if self.messages else ""
        acceptance_signals = ("yes", "include", "adjacent", "nearby", "that_is_the_center", "sounds_right")
        if not any(signal in latest for signal in acceptance_signals):
            return goal
        missing = [
            concept
            for concept in self.pending_adjacent
            if not self._concept_already_covered(concept, goal)
        ]
        if not missing:
            return goal
        return f"{goal}, plus {self._format_adjacent(missing)}"

    @staticmethod
    def _concept_already_covered(concept: str, goal: str) -> bool:
        concept_id = normalize_identifier(concept)
        goal_id = normalize_identifier(goal)
        if not concept_id:
            return True
        if concept_id in goal_id:
            return True
        parts = [part for part in concept_id.split("_and_") if part]
        return any(part in goal_id for part in parts)

    def _format_theme_clarification(self, decision: dict) -> str:
        theme = self._clean_resolved_goal(str(decision.get("candidate_theme") or ""))
        adjacent = [
            self._clean_resolved_goal(str(item))
            for item in (decision.get("adjacent_concepts") or [])
            if str(item).strip()
        ][:4]
        if not theme:
            question = decision.get("question") or self._fallback_clarification()
            return str(question).strip()
        self.pending_theme = theme
        self.pending_adjacent = adjacent
        adjacent_text = self._format_adjacent(adjacent)
        if adjacent_text:
            return (
                f"It sounds like the center might be {theme}. "
                f"That could include {adjacent_text}. Is that the right center, or would you frame it differently?"
            )
        return f"It sounds like the center might be {theme}. Is that the right center, or would you frame it differently?"

    @staticmethod
    def _format_adjacent(items: list[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return f"{', '.join(items[:-1])}, and {items[-1]}"

    @staticmethod
    def _clean_resolved_goal(goal: str) -> str:
        cleaned = " ".join(goal.split()).strip(" .")
        stray_suffixes = (" Both", " both")
        for suffix in stray_suffixes:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip(" .")
        return cleaned

    @staticmethod
    def _valid_resolved_goal(goal: str) -> bool:
        if not goal:
            return False
        lowered = goal.lower()
        return "user:" not in lowered and "assistant:" not in lowered

    @staticmethod
    def _is_confirmation(text: str) -> bool:
        normalized = normalize_identifier(text)
        return normalized in {
            "yes",
            "y",
            "yep",
            "yeah",
            "correct",
            "sounds_good",
            "looks_good",
            "create_it",
            "make_it",
            "confirm",
            "confirmed",
            "go_ahead",
            "do_it",
        }
