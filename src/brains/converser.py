import json
from enum import StrEnum

from brains.brain import Brain, CognitiveLoop, EvalLoop
from brains.prompts_converser import *




class LessonState(StrEnum):
    """State Machine

    TEACH -> TEACH, EVALUATE
    EVALUATE -> FIX, ADVANCE
    FIX -> FIX, EVALUATE
    ADVANCE -> TEACH
    """

    TEACH = "teach"
    EVALUATE = "evaluate"
    FIX = "fix"
    ADVANCE = "advance"


STATE_ENTRY_PROMPTS = {
    LessonState.EVALUATE: "Ask the user a question to evaluate the their understanding"
}


class ConversationBrain(Brain):
    LOOPS = {
        "teacher": CognitiveLoop(TEACHER_PROMPT),
        "state-evaluator": EvalLoop(EVALUATION_PROMPT, temperature=0.0),
        "distillation": CognitiveLoop(INSIGHT_EXTRACTION_PROMPT),
        # TODO: Lesson planning loop
    }
    OUTPUT_LOOP = "teacher"

    def __init__(self, messages=[]):
        super().__init__(self.LOOPS, self.OUTPUT_LOOP, messages)
        self.state = LessonState.TEACH

    def evaluate_user_message(self, user_message: str):
        self.append_message("user", user_message)
        # Evaluate what we should do next based on the user's message and the current state of the lesson
        state_response = self.get_loop_response("state-evaluator", as_json=True)
        self.update_state(state_response)
        return state_response

    def update_state(self, state_response: dict):
        print(state_response)
        understanding, confidence = state_response["understanding"], state_response["confidence"]
        new_state = None
        match self.state:
            case LessonState.TEACH:
                if understanding > 0.6 and confidence > 0.75:
                    new_state = LessonState.EVALUATE
            case LessonState.EVALUATE:
                if understanding > 0.8 and confidence > 0.75:
                    new_state = LessonState.ADVANCE
                else:
                    new_state = LessonState.FIX
            case LessonState.FIX:
                if understanding > 0.8 and confidence > 0.75:
                    new_state = LessonState.ADVANCE

        if new_state is not None:
            print("Updating state:", new_state)
            self.state = new_state
            prompt = STATE_ENTRY_PROMPTS.get(new_state, "")
            self.append_message("system", f"Entering {new_state} mode. Reason: {state_response['evidence']}. {prompt}")


def test_evaluator():
    with open("data/conversations/kalman.json", "r", encoding="utf-8") as f:
        conversation = json.load(f)[1:]

    agent = ConversationBrain()
    user_indices = [i for i, m in enumerate(conversation) if m["role"] == "user"]

    for i in user_indices:
        agent.set_messages(conversation[:i-1])
        responses = agent.respond(conversation[i]["content"])
        import time
        time.sleep(5)
        for r in responses:
            print(r)



if __name__ == "__main__":
    test_evaluator()

    # conversation = [
    #     {"role": "user", "content": "I'm not sure I get how magnetic materials work and how they explain permeability"},
    #     {"role": "assistant", "content": "Let's start by considering a simple model to understand magnetic fields and materials. Imagine you have a bar magnet, like a compass needle or a small iron nail that has been magnetized.\n\nMagnetic materials are substances (like iron, nickel, cobalt) that can be magnetized because their atomic structures allow them to align in such a way as to create an overall magnetic field. This alignment is due to the presence of unpaired electrons in the atoms of these materials, which have a preferred orientation within the material.\n\nNow, let's introduce the concept of permeability. Permeability (μ) is a measure of how easily a material can be magnetized and how much it will react when placed in a magnetic field. It’s often described as a property that affects the strength of the magnetic flux through a material.\n\nFor an ideal conductor or vacuum, the permeability is constant and given by the permeability of free space (μ₀), which is approximately \\(4\\pi \\times 10^{-7} \\) Tesla meters per ampere (\\(Tm/A\\)).\n\nIn real materials, however, there are tiny defects like impurities in the material structure or grain boundaries where different regions have slightly varying magnetic properties. These materials do not align perfectly and thus do not allow magnetic fields to penetrate as freely as a perfect vacuum would.\n\nWhen you place a magnet near a magnetic material, it can create a magnetic field that interacts with the atomic dipoles within the material. The strength of this interaction depends on the material’s permeability. Materials like iron are ferromagnetic and have high permeability, meaning they allow magnetic fields to penetrate more easily than diamagnetic materials (which are repelled by magnets) or paramagnetic materials (which are attracted but not strongly).\n\nTo build a deeper understanding, consider an experiment: place a piece of iron in the vicinity of another magnet. The iron will become magnetized and align its atomic dipoles with those of the external magnetic field. This phenomenon is crucial for applications like electromagnets used in motors, generators, and transformers.\n\nIf you need to delve into more complex aspects or specific examples, please let me know!"},
    # ]

    # agent = ConversationBrain(messages=conversation)
    # with open("data/conversations/induction.json", "r", encoding="utf-8") as f:
    #     conversation = json.load(f)[1:]
    # response = agent.respond("But why do some materials have higher permeability than others? What's happening at the atomic level?")
    # print(response)
