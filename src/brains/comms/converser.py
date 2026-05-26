from enum import StrEnum

from brains.comms.agent_base import Brain, Task
from brains.comms.prompts_converser import *


class LessonState(StrEnum):
    TEACH = "teach"
    EVALUATE = "evaluate"
    FIX = "fix"
    ADVANCE = "advance"


STATE_ENTRY_PROMPTS = {
    LessonState.EVALUATE: "Ask the user a question to evaluate their understanding."
}


class ConversationBrain(Brain):
    def __post_init__(self):
        self.teacher_task = Task("teacher", TEACHER_PROMPT, visible_history=12, temperature=0.5)
        self.state_eval_task = Task(
            "state_eval",
            EVALUATION_PROMPT,
            context_format="transcript",
            visible_history=12,
            output_format="json",
            temperature=0.0,
        )
        self.distill_task = Task(
            "insight_distiller",
            INSIGHT_EXTRACTION_PROMPT,
            context_format="transcript",
            visible_history=20,
            output_format="json",
            temperature=0.5,
        )
        self.state = LessonState.TEACH
        self.state_prompt = ""
        self.state_transition_confidence_threshold = 0.75

    def respond(self, user_message: str):
        self.evaluate_user_message(user_message)
        dynamic_prompts = [self.state_prompt] if self.state_prompt else []
        yield from self.stream_task(self.teacher_task, dynamic_prompts=dynamic_prompts)

    def evaluate_user_message(self, user_message: str):
        self.add_usr_msg(user_message)
        state_response = self.run_task_json(self.state_eval_task)
        self.update_state(state_response)
        return state_response

    def update_state(self, state_response: dict):
        print(state_response)
        understanding = state_response["understanding"]
        confidence = state_response["confidence"]
        new_state = None

        match self.state:
            case LessonState.TEACH:
                if understanding > 0.6 and confidence > self.state_transition_confidence_threshold:
                    new_state = LessonState.EVALUATE
            case LessonState.EVALUATE:
                new_state = LessonState.ADVANCE if understanding > 0.8 else LessonState.FIX
            case LessonState.FIX:
                if understanding > 0.8 and confidence > self.state_transition_confidence_threshold:
                    new_state = LessonState.ADVANCE

        if new_state is not None:
            self.transition_to(new_state, state_response)

    def transition_to(self, new_state: LessonState, state_response: dict):
        print("Updating state:", new_state)
        self.state = new_state
        prompt = STATE_ENTRY_PROMPTS.get(new_state, "")
        self.state_prompt = f"Current mode: {new_state}. Reason: {state_response['evidence']}. {prompt}"
