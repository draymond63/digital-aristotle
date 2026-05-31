from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import TypeVar

from teacher.agent.conversation import Conversation
from teacher.agent.providers import Agent
from teacher.agent.types import ResponseObject, Task


ResponseT = TypeVar("ResponseT", bound=ResponseObject)
logger = logging.getLogger(__name__)


class TaskConversation:
    """Provide shared task execution and conversation logging helpers."""

    def __init__(self, agent: Agent | None = None, messages=None):
        """Initialize with an agent and optional seed messages."""
        self.agent = agent or Agent()
        self.convo = Conversation(messages)

    @property
    def conversation(self) -> Conversation:
        """Return the active conversation."""
        return self.convo

    @conversation.setter
    def conversation(self, value: Conversation):
        """Replace the active conversation."""
        self.convo = value

    def add_user_message(self, user_message: str):
        """Append a visible user message to the active conversation."""
        self.convo.append_user(user_message)

    def run_task_json(
        self,
        task: Task[ResponseT],
        conversation: Conversation | None = None,
        log_conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
        visible: bool = False,
        default: ResponseT | None = None,
        error_message: str | None = None,
    ) -> ResponseT | None:
        """Run a structured task and append its validated result."""
        conversation = conversation or self.convo
        log_conversation = log_conversation or conversation
        dynamic_prompts = dynamic_prompts or []
        input_messages = self.agent.build_task_messages(task, conversation, dynamic_prompts, packet)
        try:
            result = self.agent.run_task_json(task, conversation, dynamic_prompts, packet)
        except Exception:
            logger.exception(error_message or f"Failed to run {task.name}")
            if default is None:
                raise
            return default
        log_conversation.append_task_result(
            task,
            json.dumps(result.json_data()),
            visible=visible,
            dynamic_prompts=dynamic_prompts,
            input_messages=input_messages,
        )
        return result

    def stream_task(
        self,
        task: Task,
        conversation: Conversation | None = None,
        log_conversation: Conversation | None = None,
        dynamic_prompts: list[str] | None = None,
        packet: str | None = None,
        visible: bool = True,
    ):
        """Stream a task and append its complete response."""
        conversation = conversation or self.convo
        log_conversation = log_conversation or conversation
        dynamic_prompts = dynamic_prompts or []
        input_messages = self.agent.build_task_messages(task, conversation, dynamic_prompts, packet)
        response = ""
        for content in self.agent.stream_task(task, conversation, dynamic_prompts, packet):
            response = f"{response}\n\n{content}" if response else content
            yield content
        if response:
            log_conversation.append_task_result(
                task,
                response,
                visible=visible,
                dynamic_prompts=dynamic_prompts,
                input_messages=input_messages,
            )

    def save(self):
        """Persist the current conversation under a timestamp filename."""
        filename = datetime.now().isoformat(timespec="seconds").replace(":", "-")
        self.convo.save(filename)

    @property
    def num_messages(self):
        """Return the number of active conversation messages."""
        return len(self.convo)

    def set_convo(self, convo: Conversation):
        """Replace the active conversation object."""
        self.convo = convo
