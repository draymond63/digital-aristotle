from enum import StrEnum
import re

from brains.comms.agent_base import Brain, Task, get_control_model, get_teacher_model
from brains.comms.prompts_converser import *


class LessonState(StrEnum):
    TEACH = "teach"
    EVALUATE = "evaluate"
    FIX = "fix"
    ADVANCE = "advance"


STATE_ENTRY_PROMPTS = {
    LessonState.TEACH: (
        "Teach one small conceptual step. Keep it concise, concrete, and connected "
        "to the user's last message."
    ),
    LessonState.EVALUATE: (
        "Your whole reply should be exactly one focused conceptual check question. "
        "Make it feel like a natural conversation, not a quiz. Do not explain first."
    ),
    LessonState.FIX: (
        "Repair the specific confusion or misconception before moving on. Use a "
        "different angle than the prior explanation. Keep it to one short paragraph."
    ),
    LessonState.ADVANCE: (
        "Briefly acknowledge the user's demonstrated understanding, then introduce "
        "the next small conceptual step."
    ),
}


class ConversationBrain(Brain):
    def __post_init__(self):
        self.teacher_task = Task(
            "teacher",
            TEACHER_PROMPT,
            model=get_teacher_model(),
            visible_history=12,
            dynamic_after_context=True,
            temperature=0.35,
            num_predict=360,
        )
        self.check_task = Task(
            "understanding_check",
            UNDERSTANDING_CHECK_PROMPT,
            model=get_control_model(),
            visible_history=12,
            dynamic_after_context=True,
            temperature=0.2,
            num_predict=80,
        )
        self.state_eval_task = Task(
            "state_eval",
            EVALUATION_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=12,
            output_format="json",
            temperature=0.0,
            num_predict=120,
        )
        self.distill_task = Task(
            "insight_distiller",
            INSIGHT_EXTRACTION_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=20,
            output_format="json",
            temperature=0.3,
            num_predict=360,
        )
        self.state = LessonState.TEACH
        self.state_prompt = ""
        self.mode_prompt = self._build_mode_prompt(LessonState.TEACH, "Starting a fresh teaching turn.")
        self.state_transition_confidence_threshold = 0.7

    def respond(self, user_message: str):
        self.evaluate_user_message(user_message)
        dynamic_prompts = [
            prompt for prompt in (self.state_prompt, self.mode_prompt)
            if prompt
        ]
        if self.state == LessonState.EVALUATE:
            yield self.run_understanding_check(dynamic_prompts)
        else:
            yield from self.stream_task(self.teacher_task, dynamic_prompts=dynamic_prompts)
        if self.state == LessonState.ADVANCE:
            self.transition_to(
                LessonState.TEACH,
                {"evidence": "Advanced to a new conceptual step; resume normal teaching."},
            )

    def evaluate_user_message(self, user_message: str):
        self.add_usr_msg(user_message)
        state_response = self.run_task_json(self.state_eval_task)
        self.update_state(state_response)
        return state_response

    def update_state(self, state_response: dict):
        understanding = state_response.get("understanding", 0.0)
        confidence = state_response.get("confidence", 0.0)
        intent = state_response.get("intent", "continue")
        evidence = state_response.get("evidence", "No evidence supplied.")
        new_state = None

        if intent in {"new_question", "topic_switch"}:
            self.transition_to(
                LessonState.TEACH,
                {**state_response, "evidence": evidence},
            )
            return

        has_assistant_context = self._has_recent_assistant_turn()

        if confidence < self.state_transition_confidence_threshold:
            self.mode_prompt = self._build_mode_prompt(
                self.state,
                f"Low-confidence state estimate: {evidence}",
            )
            return

        if has_assistant_context and understanding <= 0.5:
            self.transition_to(LessonState.FIX, state_response)
            return

        match self.state:
            case LessonState.TEACH:
                if understanding > 0.65 and has_assistant_context:
                    new_state = LessonState.EVALUATE
            case LessonState.EVALUATE:
                new_state = LessonState.ADVANCE if understanding > 0.8 else LessonState.FIX
            case LessonState.FIX:
                if understanding > 0.8:
                    new_state = LessonState.ADVANCE
            case LessonState.ADVANCE:
                new_state = LessonState.TEACH

        if new_state is not None:
            self.transition_to(new_state, state_response)
        else:
            self.mode_prompt = self._build_mode_prompt(self.state, evidence)

    def transition_to(self, new_state: LessonState, state_response: dict):
        self.state = new_state
        self.mode_prompt = self._build_mode_prompt(
            new_state,
            state_response.get("evidence", "No evidence supplied."),
        )

    def _build_mode_prompt(self, state: LessonState, evidence: str):
        prompt = STATE_ENTRY_PROMPTS.get(state, "")
        return f"Current teaching mode: {state.value}. Reason: {evidence}. {prompt}"

    def _has_recent_assistant_turn(self):
        return any(message.role == "assistant" for message in self.convo.visible_messages())

    def run_understanding_check(self, dynamic_prompts: list[str]):
        input_messages = self.agent.build_task_messages(self.check_task, self.convo, dynamic_prompts)
        content = self.agent.run_task(self.check_task, self.convo, dynamic_prompts)
        question = self._extract_last_question(content)
        self.convo.append_task_result(
            self.check_task,
            question,
            visible=True,
            dynamic_prompts=dynamic_prompts,
            input_messages=input_messages,
        )
        return question

    @staticmethod
    def _extract_last_question(content: str):
        matches = re.findall(r"[^?.!]*\?", content.strip(), flags=re.DOTALL)
        if not matches:
            return content.strip()
        return re.sub(r"\s+", " ", matches[-1]).strip()
