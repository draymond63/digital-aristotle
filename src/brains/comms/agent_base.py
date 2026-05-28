import json
import os
import dotenv
from dataclasses import dataclass, asdict, field
from typing import Generator, Literal, get_args
from ollama import Client
from openai import OpenAI


RoleType = Literal["user", "system", "assistant"]
ROLES = get_args(RoleType)
ContextFormat = Literal["messages", "transcript", "packet"]
OutputFormat = Literal["text", "json"]
ProviderType = Literal["ollama", "openai"]
OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")
LOCAL_TEACHER_MODEL = "phi4-mini:3.8b-q4_K_M"
LOCAL_CONTROL_MODEL = "qwen2.5:3b-instruct-q4_K_M"
API_TEACHER_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class Task:
    name: str
    static_prompt: str
    model: str | None = None
    context_format: ContextFormat = "messages"
    visible_history: int | None = None
    dynamic_after_context: bool = False
    output_format: OutputFormat = "text"
    # Model parameters
    temperature: float = 0.5
    num_ctx: int = 4096
    num_predict: int = 1000
    top_p: float = 0.85
    repeat_penalty: float = 1.12


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
    def __init__(self, entries: list[LogEntry] | None = None):
        entries = entries or []
        assert isinstance(entries, list), f"Expected list[LogEntry], received {type(entries)}"
        self._entries = entries

    def save(self, filename: str):
        os.makedirs("data/conversations", exist_ok=True)
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
    def __init__(self):
        dotenv.load_dotenv()
        self.clients = {}

    @staticmethod
    def _provider_for_model(model: str) -> ProviderType:
        if model.startswith(OPENAI_MODEL_PREFIXES):
            return "openai"
        return "ollama"

    def _client_for_provider(self, provider: ProviderType):
        if provider not in self.clients:
            self.clients[provider] = self._build_client(provider)
        return self.clients[provider]

    @staticmethod
    def _build_client(provider: ProviderType):
        if provider == "ollama":
            return Client()
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("Set OPENAI_API_KEY to use an OpenAI model")
        return OpenAI()

    def run_task(
        self,
        task: Task,
        conversation: Conversation,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> str:
        response = self._generate_task(task, conversation, dynamic_prompts, packet)
        return self._message_content(response)

    def run_task_json(
        self,
        task: Task,
        conversation: Conversation,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> dict | list:
        response = self._generate_task(task, conversation, dynamic_prompts, packet, format="json")
        try:
            return json.loads(self._message_content(response))
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
        return self._generate(
            messages,
            model=task.model,
            temperature=task.temperature,
            num_ctx=task.num_ctx,
            num_predict=task.num_predict,
            top_p=task.top_p,
            repeat_penalty=task.repeat_penalty,
            **kwargs,
        )

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

    def _generate(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature=0.7,
        num_ctx=4096,
        num_predict=220,
        top_p=0.85,
        repeat_penalty=1.12,
        **kwargs,
    ):
        if model is None:
            raise ValueError("Task model must be specified")
        provider = self._provider_for_model(model)
        if provider == "openai":
            return self._generate_openai(
                messages,
                model=model,
                temperature=temperature,
                num_predict=num_predict,
                top_p=top_p,
                **kwargs,
            )

        options = {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
        }
        response = self._client_for_provider("ollama").chat(
            model=model,
            messages=messages,
            options=options,
            **kwargs
        )
        return response

    def _generate_openai(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature=0.7,
        num_predict=220,
        top_p=0.85,
        stream=False,
        format: str | None = None,
        **kwargs,
    ):
        kwargs.pop("options", None)
        request = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_completion_tokens": num_predict,
            **kwargs,
        }
        if format == "json":
            request["response_format"] = {"type": "json_object"}
        if stream:
            request["stream"] = True
            return self._client_for_provider("openai").chat.completions.create(**request)

        return self._client_for_provider("openai").chat.completions.create(**request)

    @staticmethod
    def _message_content(response) -> str:
        if hasattr(response, "message"):
            return response.message.content
        return response.choices[0].message.content or ""

    @staticmethod
    def _chunk_content(chunk) -> str:
        if hasattr(chunk, "message"):
            return chunk.message.content
        if not chunk.choices:
            return ""
        return chunk.choices[0].delta.content or ""

    @staticmethod
    def _chunk_responses(response: Generator, chunk_on="\n\n") -> Generator[str, None, None]:
        buffer = ""
        for chunk in response:
            content = Agent._chunk_content(chunk)
            if not content:
                continue
            buffer += content
            while chunk_on in buffer:
                split_index = buffer.index(chunk_on)
                piece = buffer[:split_index].strip()
                buffer = buffer[split_index + 2:]
                if piece:
                    yield piece
        if buffer.strip():
            yield buffer.strip()


def get_teacher_model():
    dotenv.load_dotenv()
    if os.getenv("USE_API") is not None:
        return API_TEACHER_MODEL
    return LOCAL_TEACHER_MODEL


def get_control_model():
    dotenv.load_dotenv()
    if os.getenv("USE_API") is not None:
        return API_TEACHER_MODEL
    return LOCAL_CONTROL_MODEL
