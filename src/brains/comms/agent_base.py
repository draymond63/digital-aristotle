import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from typing import Generator, Literal, get_args
from ollama import ChatResponse
from ollama import Client
from datetime import datetime


RoleType = Literal["user", "system", "assistant"]
ROLES = get_args(RoleType)
ContextFormat = Literal["messages", "transcript", "packet"]
OutputFormat = Literal["text", "json"]


@dataclass(frozen=True)
class Task:
    name: str
    static_prompt: str
    context_format: ContextFormat = "messages"
    visible_history: int | None = None
    dynamic_after_context: bool = False
    output_format: OutputFormat = "text"
    temperature: float = 0.5


@dataclass
class LogEntry:
    role: RoleType
    content: str
    task_name: str | None = None
    visible: bool = True
    dynamic_prompts: list[str] = field(default_factory=list)
    input_messages: list[dict[str, str]] = field(default_factory=list)

    @property
    def source(self) -> str:
        return self.task_name or self.role

    def json(self, full=False):
        if not full and not self.task_name and self.visible and not self.dynamic_prompts and not self.input_messages:
            return {"content": self.content, "source": self.role}
        return asdict(self)

    def to_api(self):
        return {"role": self.role, "content": self.content}


class Conversation:
    def __init__(self, entries: list[LogEntry] = []):
        assert isinstance(entries, list), f"Expected list[LogEntry], received {type(entries)}"
        self._entries = entries

    def save(self, filename: str):
        with open(f"data/conversations/{filename}.json", "w+", encoding="utf-8") as f:
            json.dump(self.json(full=True), f)

    @classmethod
    def load(cls, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            entries = json.load(f)
        return Conversation([cls._load_entry(entry) for entry in entries])

    @staticmethod
    def _load_entry(entry: dict):
        if "role" in entry:
            return LogEntry(**entry)
        source = entry["source"]
        role = source if source in ROLES else "system"
        task_name = None if source in ROLES else source
        visible = source in ("user", "assistant")
        return LogEntry(role=role, content=entry["content"], task_name=task_name, visible=visible)

    def append_user(self, content: str):
        self.append_entry(LogEntry(role="user", content=content))

    def append_task_result(
        self,
        task: Task,
        content: str,
        role: RoleType = "assistant",
        visible: bool = True,
        dynamic_prompts: list[str] | None = None,
        input_messages: list[dict[str, str]] | None = None,
    ):
        self.append_entry(LogEntry(
            role=role,
            content=content,
            task_name=task.name,
            visible=visible,
            dynamic_prompts=dynamic_prompts or [],
            input_messages=input_messages or [],
        ))

    def append_entry(self, entry: LogEntry):
        print(entry)
        self._entries.append(entry)

    def copy(self):
        return Conversation(self._entries.copy())

    def json(self, full=False):
        return [m.json(full=full) for m in self._entries]
    
    def to_api(self):
        return [m.to_api() for m in self._entries]

    def visible_messages(self):
        return Conversation([
            entry for entry in self._entries
            if entry.visible and entry.role in ("user", "assistant")
        ])

    def tail(self, count: int | None):
        if count is None:
            return self.copy()
        return Conversation(self._entries[-count:])
    
    def __len__(self):
        return len(self._entries)
    
    def __iter__(self):
        yield from self._entries

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._entries[key]
        return Conversation(self._entries[key])


class Agent:
    def __init__(self, model='qwen2.5:3b-instruct-q4_K_M'):
        self.model = model
        self.client = Client()

    def run_task(
        self,
        task: Task,
        conversation: Conversation,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> str:
        response = self._generate_task(task, conversation, dynamic_prompts, packet)
        return response.message.content

    def run_task_json(
        self,
        task: Task,
        conversation: Conversation,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> dict | list:
        response = self._generate_task(task, conversation, dynamic_prompts, packet, format="json")
        try:
            return json.loads(response.message.content)
        except Exception as e:
            raise RuntimeError(f"Failed to decode: {response}") from e

    def stream_task(
        self,
        task: Task,
        conversation: Conversation,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ):
        responses = self._generate_task(task, conversation, dynamic_prompts, packet, stream=True)
        for content in self._chunk_responses(responses):
            yield content

    def build_task_messages(
        self,
        task: Task,
        conversation: Conversation,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> list[dict[str, str]]:
        dynamic_prompts = dynamic_prompts or []
        messages = [{"role": "system", "content": task.static_prompt}]
        context = self._format_task_context(task, conversation, packet)

        if not task.dynamic_after_context:
            messages.extend({"role": "system", "content": prompt} for prompt in dynamic_prompts)
        messages.extend(context)
        if task.dynamic_after_context:
            messages.extend({"role": "system", "content": prompt} for prompt in dynamic_prompts)

        return messages

    def _generate_task(self, task: Task, conversation: Conversation, dynamic_prompts=None, packet=None, **kwargs):
        messages = self.build_task_messages(task, conversation, dynamic_prompts, packet)
        return self._generate(messages, temperature=task.temperature, **kwargs)

    def _format_task_context(self, task: Task, conversation: Conversation, packet: str | None):
        visible_context = conversation.visible_messages().tail(task.visible_history)
        if task.context_format == "messages":
            return visible_context.to_api()
        if task.context_format == "transcript":
            return [{"role": "user", "content": self._build_transcript(visible_context)}]
        if task.context_format == "packet":
            assert packet is not None, f"Task {task.name} requires packet context"
            return [{"role": "user", "content": packet}]
        raise ValueError(f"Unknown context format: {task.context_format}")

    @staticmethod
    def _build_transcript(conversation: Conversation):
        transcript = "BEGIN TRANSCRIPT\n"
        for message in conversation:
            transcript += f"{message.role.upper()}: {message.content}\n\n"
        transcript += "END TRANSCRIPT"
        return transcript

    def _generate(self, messages: list[dict[str, str]], temperature=0.7, **kwargs):
        response = self.client.chat(
            model=self.model,
            messages=messages,
            options={'temperature': temperature},
            **kwargs
        )
        return response

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



class Brain(ABC):
    """Base class for stateful task-driven conversation loops."""

    def __init__(self, messages=[]):
        self.agent = Agent()
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
        self.convo.append_user(user_message)

    def run_task(
        self,
        task: Task,
        conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
        visible: bool = True,
    ) -> str:
        conversation = conversation or self.convo
        dynamic_prompts = dynamic_prompts or []
        input_messages = self.agent.build_task_messages(task, conversation, dynamic_prompts, packet)
        content = self.agent.run_task(task, conversation, dynamic_prompts, packet)
        self.convo.append_task_result(
            task,
            content,
            visible=visible,
            dynamic_prompts=dynamic_prompts,
            input_messages=input_messages,
        )
        return content

    def run_task_json(
        self,
        task: Task,
        conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
        visible: bool = False,
    ) -> dict | list:
        conversation = conversation or self.convo
        dynamic_prompts = dynamic_prompts or []
        input_messages = self.agent.build_task_messages(task, conversation, dynamic_prompts, packet)
        result = self.agent.run_task_json(task, conversation, dynamic_prompts, packet)
        self.convo.append_task_result(
            task,
            json.dumps(result),
            visible=visible,
            dynamic_prompts=dynamic_prompts,
            input_messages=input_messages,
        )
        return result

    def stream_task(
        self,
        task: Task,
        conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
        visible: bool = True,
    ):
        conversation = conversation or self.convo
        dynamic_prompts = dynamic_prompts or []
        input_messages = self.agent.build_task_messages(task, conversation, dynamic_prompts, packet)
        for content in self.agent.stream_task(task, conversation, dynamic_prompts, packet):
            self.convo.append_task_result(
                task,
                content,
                visible=visible,
                dynamic_prompts=dynamic_prompts,
                input_messages=input_messages,
            )
            yield content

    def save(self):
        filename = datetime.now().isoformat(timespec="seconds").replace(":", "-")
        self.convo.save(filename)

    @property
    def num_messages(self):
        return len(self.convo)

    def set_convo(self, convo: Conversation):
        self.convo = convo



