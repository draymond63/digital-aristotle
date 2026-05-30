from __future__ import annotations

from collections.abc import Callable

from brains.comms.agent_base import Agent, Conversation, Task, get_control_model
from brains.comms.prompts_session import GOAL_INTAKE_EVALUATOR_PROMPT, GOAL_INTAKE_RESPONDER_PROMPT
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
        self.conversation = Conversation()
        self.pending_theme: str | None = None
        self.pending_adjacent: list[str] = []
        self.pending_resolved_goal: str | None = None
        self.evaluator_task = Task(
            "goal_intake_evaluator",
            GOAL_INTAKE_EVALUATOR_PROMPT,
            model=get_control_model(),
            visible_history=None,
            output_format="json",
            temperature=0.1,
            num_predict=220,
        )
        self.responder_task = Task(
            "goal_intake_responder",
            GOAL_INTAKE_RESPONDER_PROMPT,
            model=get_control_model(),
            visible_history=None,
            temperature=0.35,
            num_predict=220,
        )

    def clear(self):
        self.messages = []
        self.conversation = Conversation()
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
        if self.pending_resolved_goal and self._is_confirmation(text):
            resolved_goal = self.pending_resolved_goal
            self.clear()
            prefix = f"Great. I will make this the track: {resolved_goal}\n\n"
            return prefix + self.create_goal(resolved_goal)

        if mode == "goal_confirm":
            self.set_mode("goal_intake")

        self.messages.append(text.strip())
        self.conversation.append_user(text.strip())
        decision = self._evaluate()
        if len(self.messages) == 1:
            decision = {
                **decision,
                "status": "clarify",
                "resolved_goal": "",
                "response_intent": "shape_theme" if decision.get("candidate_theme") else "clarify_outcome",
                "rationale": "Goal creation requires at least one clarification turn.",
            }
        if decision.get("status") == "ready" and decision.get("resolved_goal"):
            resolved_goal = self._clean_resolved_goal(decision["resolved_goal"])
            if not self._valid_resolved_goal(resolved_goal):
                resolved_goal = self._fallback_resolved_goal()
            resolved_goal = self._include_confirmed_adjacent_concepts(resolved_goal)
            self.pending_resolved_goal = resolved_goal
            self.set_mode("goal_confirm")
            decision = {**decision, "resolved_goal": resolved_goal, "response_intent": "propose_goal"}
        response = self._respond(decision)
        self._append_intake_response(response)
        return response

    def _evaluate(self) -> dict:
        try:
            decision = self.agent.run_task_json(
                self.evaluator_task,
                self.conversation,
                dynamic_prompts=[f"User profile:\n{self.profile}"],
            )
        except Exception:
            return self._fallback_decision()
        if not isinstance(decision, dict):
            return self._fallback_decision()
        if len(self.messages) < 2:
            return {
                "status": "clarify",
                "resolved_goal": "",
                "candidate_theme": decision.get("candidate_theme") or "",
                "adjacent_concepts": decision.get("adjacent_concepts") or [],
                "response_intent": decision.get("response_intent") or "shape_theme",
                "rationale": "Goal creation requires at least one clarification turn.",
                "fallback": bool(decision.get("fallback")),
            }
        return decision

    def _respond(self, decision: dict) -> str:
        self._store_candidate_context(decision)
        if decision.get("fallback"):
            return self._fallback_response(decision)
        try:
            response = self.agent.run_task(
                self.responder_task,
                self.conversation,
                dynamic_prompts=[
                    f"User profile:\n{self.profile}",
                    f"Evaluator decision:\n{decision}",
                ],
            )
        except Exception:
            response = self._fallback_response(decision)
        return response.strip() or self._fallback_response(decision)

    def _append_intake_response(self, text: str):
        self.conversation.append_task_result(self.responder_task, text)

    def _fallback_decision(self) -> dict:
        return {
            "status": "clarify",
            "resolved_goal": "",
            "candidate_theme": self.pending_theme or "",
            "adjacent_concepts": self.pending_adjacent,
            "response_intent": "clarify_outcome",
            "rationale": "Could not evaluate confidently.",
            "fallback": True,
        }

    def _fallback_response(self, decision: dict) -> str:
        if decision.get("status") == "ready" and decision.get("resolved_goal"):
            return (
                f"This is the track I would make: {decision['resolved_goal']}\n\n"
                "Say 'create it' when that feels right, or tell me what still feels off."
            )
        theme = decision.get("candidate_theme") or self.pending_theme
        adjacent = self._format_adjacent(decision.get("adjacent_concepts") or self.pending_adjacent)
        if theme and adjacent:
            return (
                f"I think the center might be {theme}. It could branch into {adjacent}.\n\n"
                "Which part feels closest to what you actually want to be able to do?"
            )
        if theme:
            return (
                f"I think the center might be {theme}.\n\n"
                "What would make that useful for you: intuition, practical use, or deeper theory?"
            )
        return (
            "I hear a cluster of examples, but not quite the center yet.\n\n"
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

    def _store_candidate_context(self, decision: dict):
        theme = self._clean_resolved_goal(str(decision.get("candidate_theme") or ""))
        adjacent = [
            self._clean_resolved_goal(str(item))
            for item in (decision.get("adjacent_concepts") or [])
            if str(item).strip()
        ][:4]
        if theme:
            self.pending_theme = theme
        if adjacent:
            self.pending_adjacent = adjacent

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
