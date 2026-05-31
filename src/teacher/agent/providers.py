from __future__ import annotations

import json
import os
from typing import Generator, Literal

import dotenv
from ollama import Client
from openai import OpenAI

from teacher.agent.conversation import Conversation
from teacher.agent.types import ResponseT, Task


ProviderType = Literal["ollama", "openai"]
OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")
LOCAL_TEACHER_MODEL = "phi4-mini:3.8b-q4_K_M"
LOCAL_CONTROL_MODEL = "qwen2.5:3b-instruct-q4_K_M"
API_TEACHER_MODEL = "gpt-4.1-mini"


class Agent:
    """Run text and structured tasks against configured model providers."""

    def __init__(self):
        """Load environment configuration and initialize provider cache."""
        dotenv.load_dotenv()
        self.clients = {}

    @staticmethod
    def _provider_for_model(model: str) -> ProviderType:
        """Choose a provider from a model name."""
        if model.startswith(OPENAI_MODEL_PREFIXES):
            return "openai"
        return "ollama"

    def _client_for_provider(self, provider: ProviderType):
        """Return a cached provider client."""
        if provider not in self.clients:
            self.clients[provider] = self._build_client(provider)
        return self.clients[provider]

    @staticmethod
    def _build_client(provider: ProviderType):
        """Build a provider client."""
        if provider == "ollama":
            return Client()
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("Set OPENAI_API_KEY to use an OpenAI model")
        return OpenAI()

    def run_task(
        self,
        task: Task,
        conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> str:
        """Run a task and return text content."""
        response = self._generate_task(task, conversation, dynamic_prompts, packet)
        return self._message_content(response)

    def run_task_json(
        self,
        task: Task[ResponseT],
        conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> ResponseT:
        """Run a structured task and validate the JSON response."""
        if task.output_format is None:
            raise ValueError(f"Task {task.name} does not define a response object")
        response = self._generate_task(task, conversation, dynamic_prompts, packet, format="json")
        try:
            return task.output_format.model_validate(json.loads(self._message_content(response)))
        except Exception as e:
            raise RuntimeError(f"Failed to decode: {response}") from e

    def stream_task(
        self,
        task: Task,
        conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ):
        """Stream a task response as paragraph chunks."""
        responses = self._generate_task(task, conversation, dynamic_prompts, packet, stream=True)
        for content in self._chunk_responses(responses):
            yield content

    def build_task_messages(
        self,
        task: Task,
        conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
    ) -> list[dict[str, str]]:
        """Build provider messages for a task."""
        conversation = conversation or Conversation()
        dynamic_prompts = dynamic_prompts or []
        messages = [{"role": "system", "content": task.static_prompt}]
        context = self._format_task_context(task, conversation, packet)

        if not task.dynamic_after_context:
            messages.extend({"role": "system", "content": prompt} for prompt in dynamic_prompts)
        messages.extend(context)
        if task.dynamic_after_context:
            messages.extend({"role": "system", "content": prompt} for prompt in dynamic_prompts)

        return messages

    def _generate_task(self, task: Task, conversation: Conversation | None = None, dynamic_prompts=None, packet=None, **kwargs):
        """Generate a provider response for a task."""
        conversation = conversation or Conversation()
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
        """Format task context according to the task contract."""
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
        """Build a plain transcript from visible conversation entries."""
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
        """Generate a raw provider response."""
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
        """Generate a raw OpenAI chat completion response."""
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
        """Extract message text from Ollama or OpenAI responses."""
        if hasattr(response, "message"):
            return response.message.content
        return response.choices[0].message.content or ""

    @staticmethod
    def _chunk_content(chunk) -> str:
        """Extract chunk text from Ollama or OpenAI streams."""
        if hasattr(chunk, "message"):
            return chunk.message.content
        if not chunk.choices:
            return ""
        return chunk.choices[0].delta.content or ""

    @staticmethod
    def _chunk_responses(response: Generator, chunk_on="\n\n") -> Generator[str, None, None]:
        """Yield buffered stream chunks split on paragraph breaks."""
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
    """Return the configured teacher model name."""
    dotenv.load_dotenv()
    if os.getenv("USE_API") is not None:
        return API_TEACHER_MODEL
    return LOCAL_TEACHER_MODEL


def get_control_model():
    """Return the configured control model name."""
    dotenv.load_dotenv()
    if os.getenv("USE_API") is not None:
        return API_TEACHER_MODEL
    return LOCAL_CONTROL_MODEL
