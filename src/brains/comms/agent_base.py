# C:\Users\dan\AppData\Local\Programs\Ollama\ollama.exe pull qwen3.5:9b

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from enum import StrEnum
from typing import Generator, Callable, Optional, Literal, get_args
from ollama import ChatResponse
from ollama import Client, AsyncClient
# from transformers import AutoTokenizer
from datetime import datetime

from brains.comms.prompts_system import TOPIC_ID_PROMPT


RoleType = Literal["user", "system", "assistant"]
ROLES = get_args(RoleType)


@dataclass
class Message:
    content: str
    source: str | RoleType

    def json(self, full=False):
        return asdict(self)

    def to_api(self):
        return {"role": self.role, "content": self.content}

    @property
    def in_transcript(self):
        return self.source in ROLES

    @property
    def role(self) -> RoleType:
        if self.source in ROLES:
            return self.source
        return "system"


class Conversation:
    def __init__(self, messages: list[Message] = []):
        assert isinstance(messages, list), f"Expected list[Message], received {type(messages)}"
        self._messages: list[Message] = messages

    def save(self, filename: str):
        with open(f"data/conversations/{filename}.json", "w+", encoding="utf-8") as f:
            json.dump(self.json(), f)

    @classmethod
    def load(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            messages = json.load(f)
        return Conversation([Message(**m) for m in messages])

    @classmethod
    def load_api_format(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            messages = json.load(f)
        return Conversation([Message(m["content"], m["role"]) for m in messages])

    def append(self, content: str | Message, source: Optional[str] = None):
        if isinstance(content, Message):
            msg = content
            assert source is None
        else:
            assert content and source
            msg = Message(content, source)
        print(msg)
        self._messages.append(msg)

    def in_transcript(self):
        return self.filter(lambda m: m.in_transcript)

    def with_agents(self, agents: list[str]):
        return self.filter(lambda m: m.in_transcript or m.source in agents)

    def filter(self, keep: Callable[[Message], bool]):
        return Conversation([m for m in self._messages if keep(m)])

    def insert(self, index: int, value: Message):
        new_convo = self.copy()
        new_convo._messages.insert(index, value)
        return new_convo

    def copy(self):
        return Conversation(self._messages.copy())

    def json(self, full=False):
        return [m.json() for m in self._messages]
    
    def to_api(self):
        return [m.to_api() for m in self._messages]
    
    def __len__(self):
        return len(self._messages)
    
    def __iter__(self):
        yield from self._messages

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._messages[key]
        return Conversation(self._messages[key])


class Agent:
    def __init__(self, model='qwen2.5:3b-instruct-q4_K_M', max_tokens=4096):
        self.model = model
        # self.model = 'phi4-mini:3.8b-q4_K_M'
        self.client = Client()
        # self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-3B-Instruct", trust_remote_code=True)
        # self.max_tokens = max_tokens

    def get_json(self, *args, **kwargs) -> dict | list:
        response = self.get_response(*args, format="json", **kwargs)
        try:
            return json.loads(response.content)
        except Exception as e:
            raise RuntimeError(f"Failed to decode: {response}") from e

    def get_response(self, *args, **kwargs) -> Message:
        response = self._generate(*args, **kwargs)
        return self.wrap_msg(response.message.content)

    def stream_response(self,*args, **kwargs):
        responses = self._generate(*args, stream=True, **kwargs)
        for content in self._chunk_responses(responses):
            yield self.wrap_msg(content)

    def _generate(self, messages: Conversation, temperature=0.7, **kwargs):
        # print("Generating response for messages:\n", messages, end="\n\n")
        # discussion = "\n".join([msg['content'] for msg in messages])
        # tokens = self.tokenizer.encode(discussion)
        # if len(tokens) > self.max_tokens:
        #     print(f"Warning: input tokens ({len(tokens)}) exceed max_tokens ({self.max_tokens}). Consider truncating the input.")
        response = self.client.chat(
            model=self.model,
            messages=messages.to_api(),
            options={'temperature': temperature},
            **kwargs
        )
        return response

    def wrap_msg(self, content: str):
        return Message(content, "assistant")

    @staticmethod
    def _chunk_responses(response: Generator[ChatResponse, None, None], chunk_on="\n\n") -> Generator[str, None, None]:
        buffer = ""
        for chunk in response:
            content = chunk.message.content
            buffer += content
            while chunk_on in buffer:
                split_index = buffer.index(chunk_on)
                piece = buffer[:split_index].strip()
                buffer = buffer[split_index + 2:]
                if piece:
                    yield piece
        if buffer.strip():
            yield buffer.strip()


@dataclass
class TaskedAgent(Agent):
    name: str | Literal["assistant"]
    prompt: str
    temperature: float = 0.5

    def __post_init__(self):
        super().__init__() # TODO: This is a weird pattern due to the dataclass/inheritance. Should probably fix
        self.system_message = Message(self.prompt, "system")

    def stream_response(self, messages: Conversation, **kwargs):
        conversation = self._prep_agent_input(messages)
        yield from super().stream_response(conversation, temperature=self.temperature, **kwargs)

    def get_response(self, messages: Conversation, **kwargs):
        conversation = self._prep_agent_input(messages)
        content = super().get_response(conversation, temperature=self.temperature, **kwargs)
        return content

    def _prep_agent_input(self, messages: Conversation) -> Conversation:
        return messages.insert(0, self.system_message)
    
    def wrap_msg(self, content: str):
        return Message(content, source=self.name)


@dataclass
class EvalAgent(TaskedAgent):
    def _prep_agent_input(self, messages):
        transcript = self.get_transcript(messages)
        return super()._prep_agent_input(transcript)

    def get_transcript(self, messages: Conversation, last: int = None) -> Conversation:
        # TODO: Should we let the loop see it's previous system messages?
        clean_messages = messages.in_transcript() # messages.with_agents([self.name])
        if last:
            clean_messages = clean_messages[-last:]

        transcript = "BEGIN TRANSCRIPT\n"
        for message in clean_messages:
            role = message.role.upper()
            transcript += f"{role}: {message.content}\n\n"
        transcript += "END TRANSCRIPT"
        return Conversation([Message(transcript, "user")])



class Brain(ABC):
    """Class with TaskedAgents that holds the conversation and handles responses"""

    def __init__(self, messages=[]):
        self.convo = Conversation(messages)
        self.__post_init__()
    
    def __post_init__(self):
        pass

    @abstractmethod
    def respond(self, user_message: str) -> Generator[str, None, None]:
        pass

    def chat_local(self):
        while True:
            message = input("\nUser: ")
            if message == "":
                break
            list(self.respond(message))
        self.save()

    def add_usr_msg(self, user_message):
        self.convo.append(user_message, "user")

    def save(self):
        filename = datetime.now().isoformat(timespec="seconds").replace(":", "-")
        self.convo.save(filename)

    @property
    def num_messages(self):
        return len(self.convo)

    def wipe(self):
        self.set_convo(Conversation())

    def set_convo(self, convo: Conversation):
        self.convo = convo


if __name__ == "__main__":
    ...
    # from brains.prompts_system import TOPIC_ID_PROMPT
    # agent = Agent()
    # startTime = datetime.now()
    # response = agent.stream_response([{"role": "user", "content": "How is macroscopic inductance derived from the B field?"}], temperature=0.0)
    # for chunk in response:
    #     print(chunk)
    # endTime = datetime.now()
    # print(f"Time taken: {endTime - startTime}")

