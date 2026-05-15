import json
from dataclasses import dataclass
from enum import StrEnum
from pyexpat.errors import messages
from typing import Literal

from brains.agent import Agent
from brains.prompts import *




class LessonState(StrEnum):
    TEACH = "teach"
    EVALUATE = "evaluate"
    FIX = "fix"
    ADVANCE = "advance"


@dataclass
class EvaluationResult:
    response: str
    # TODO: Insights, misconceptions, etc.


@dataclass
class LoopDefinition:
    prompt: str
    temperature: float = 0.5


class Brain:
    LOOPS = {
        "teacher": LoopDefinition(TEACHER_PROMPT),
        "state-evaluator": LoopDefinition(EVALUATION_PROMPT, 0.0),
        "distillation": LoopDefinition(INSIGHT_EXTRACTION_PROMPT),
        # TODO: Lesson planning loop
    }

    def __init__(self, messages=[]):
        self.llm = Agent()
        self.state = LessonState.TEACH
        self._messages: list[dict[str, str]] = messages

    def evaluate_user_message(self, user_message: str) -> EvaluationResult:
        self.append_message("user", user_message)
        # Evaluate what we should do next based on the user's message and the current state of the lesson
        state_response = self.get_loop_response("state-evaluator", as_json=True)
        state_response
        # new_state = LessonState(state_response.strip().lower())
        # print(new_state)
        # if new_state != self.state:
        #     print(f"Transitioning from {self.state} to {new_state}")
        #     self.state = new_state
        #     self.append_message("system", f"Transitioning to state: {self.state}")        
        # # Response to user
        # response = self.get_loop_response("teacher")
        # self.append_message("assistant", response)
        # return EvaluationResult(response=response)

    def append_message(self, role: Literal["system", "assistant", "user"], content: str):
        self._messages.append({"role": role, "content": content})

    def get_loop_response(self, loop_name: str, as_json: bool = False, **kwargs) -> str | object:
        loop = self.LOOPS[loop_name]
        conversation = self.get_conversation(loop_name)
        format = "json" if as_json else ""
        response = self.llm.generate(conversation, temperature=loop.temperature, format=format, **kwargs)
        content = response.message.content
        print(content)
        if as_json:
            return json.loads(content)
        return content

    def get_conversation(self, loop_name: str) -> list[dict[str, str]]:
        system_prompt = self.LOOPS[loop_name].prompt
        match loop_name:
            case "state-evaluator":
                messages = [{"role": "user", "content": self.get_transcript()}]
            case _:
                messages = self._messages.copy()
        messages.insert(0, {"role": "system", "content": system_prompt})
        return messages

    def get_transcript(self, last: int = None) -> list[dict[str, str]]:
        transcript = "BEGIN TRANSCRIPT\n"
        clean_messages = [m for m in self._messages if m["role"] != "system"]
        if last:
            clean_messages = clean_messages[-last:]
        
        for message in clean_messages:
            role = message['role'].upper()
            content = message['content']
            transcript += f"{role}: {content}\n\n"
        transcript += "END TRANSCRIPT"
        return transcript




if __name__ == "__main__":
    brain = Brain()

    with open("data/conversation.example.json", "r", encoding="utf-8") as f:
        conversation = json.load(f)[1:]

    # conversation = [
    #     {"role": "user", "content": "I'm not sure I get how magnetic materials work and how they explain permeability"},
    #     {"role": "assistant", "content": "Let's start by considering a simple model to understand magnetic fields and materials. Imagine you have a bar magnet, like a compass needle or a small iron nail that has been magnetized.\n\nMagnetic materials are substances (like iron, nickel, cobalt) that can be magnetized because their atomic structures allow them to align in such a way as to create an overall magnetic field. This alignment is due to the presence of unpaired electrons in the atoms of these materials, which have a preferred orientation within the material.\n\nNow, let's introduce the concept of permeability. Permeability (μ) is a measure of how easily a material can be magnetized and how much it will react when placed in a magnetic field. It’s often described as a property that affects the strength of the magnetic flux through a material.\n\nFor an ideal conductor or vacuum, the permeability is constant and given by the permeability of free space (μ₀), which is approximately \\(4\\pi \\times 10^{-7} \\) Tesla meters per ampere (\\(Tm/A\\)).\n\nIn real materials, however, there are tiny defects like impurities in the material structure or grain boundaries where different regions have slightly varying magnetic properties. These materials do not align perfectly and thus do not allow magnetic fields to penetrate as freely as a perfect vacuum would.\n\nWhen you place a magnet near a magnetic material, it can create a magnetic field that interacts with the atomic dipoles within the material. The strength of this interaction depends on the material’s permeability. Materials like iron are ferromagnetic and have high permeability, meaning they allow magnetic fields to penetrate more easily than diamagnetic materials (which are repelled by magnets) or paramagnetic materials (which are attracted but not strongly).\n\nTo build a deeper understanding, consider an experiment: place a piece of iron in the vicinity of another magnet. The iron will become magnetized and align its atomic dipoles with those of the external magnetic field. This phenomenon is crucial for applications like electromagnets used in motors, generators, and transformers.\n\nIf you need to delve into more complex aspects or specific examples, please let me know!"},
    # ]

    agent = Brain(messages=conversation)

    response = agent.evaluate_user_message("But why do some materials have higher permeability than others? What's happening at the atomic level?")
    # print(response)
