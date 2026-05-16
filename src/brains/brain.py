import json
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Literal, Generator

from brains.model_api import Agent
from brains.prompts_converser import *





@dataclass
class CognitiveLoop:
    prompt: str
    temperature: float = 0.5

    def format_conversation(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        messages = messages.copy()
        messages.insert(0, {"role": "system", "content": self.prompt})
        return messages
    

class EvalLoop(CognitiveLoop):
    def format_conversation(self, messages):
        transcript = self.get_transcript(messages)
        return super().format_conversation([{"role": "user", "content": transcript}])

    def get_transcript(self, messages: list[dict[str, str]], last: int = None) -> str:
        transcript = "BEGIN TRANSCRIPT\n"
        # TODO: Should we let the loop see it's previous system messages?
        clean_messages = remove_sys_messages(messages)
        if last:
            clean_messages = clean_messages[-last:]

        for message in clean_messages:
            role = message['role'].upper()
            content = message['content']
            transcript += f"{role}: {content}\n\n"
        transcript += "END TRANSCRIPT"
        return transcript


class Brain(ABC):
    def __init__(self, loops: dict[str, CognitiveLoop], main_loop: str, messages=[]):
        self.llm = Agent()
        self._messages: list[dict[str, str]] = []
        self.set_messages(messages)
        self._loops = loops
        self._main_loop = main_loop

    def set_messages(self, messages: list[dict[str, str]]):
        self._messages = remove_sys_messages(messages)

    @property
    def num_messages(self):
        return len(self._messages)

    def respond(self, user_message: str) -> Generator[str, None, None]:
        self.evaluate_user_message(user_message)       
        # # Response to user
        response = self.stream_loop_response(self._main_loop)
        for message in response:
            self.append_message("assistant", message)
            yield message

    @abstractmethod
    def evaluate_user_message(self, user_message: str):
        ...

    def append_message(self, role: Literal["system", "assistant", "user"], content: str):
        self._messages.append({"role": role, "content": content})
        print(f"{role}: {content}\n")

    def stream_loop_response(self, loop_name: str, **kwargs) -> Generator[str, None, None]:
        loop = self._loops[loop_name]
        conversation = loop.format_conversation(self._messages)
        return self.llm.generate_chunks(conversation, temperature=loop.temperature, **kwargs)

    def get_loop_response(self, loop_name: str, as_json: bool = False, **kwargs) -> str | object:
        loop = self._loops[loop_name]
        conversation = loop.format_conversation(self._messages)
        format = "json" if as_json else ""
        content = self.llm.generate(conversation, temperature=loop.temperature, format=format, **kwargs)
        if as_json:
            return json.loads(content)
        return content
    

def remove_sys_messages(messages):
    return [m for m in messages if m["role"] != "system"]


if __name__ == "__main__":
    with open("data/conversations/induction.json", "r", encoding="utf-8") as f:
        conversation = json.load(f)[1:]
    agent = Brain(messages=conversation)
    response = agent.respond("But why do some materials have higher permeability than others? What's happening at the atomic level?")
    print(response)
