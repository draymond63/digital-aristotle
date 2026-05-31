from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import TypeVar

from brains.comms.agent_base import Agent, Conversation, ResponseObject, Task


ResponseT = TypeVar("ResponseT", bound=ResponseObject)
logger = logging.getLogger(__name__)


class TaskConversation:
    def __init__(self, agent: Agent | None = None, messages=None):
        self.agent = agent or Agent()
        self.convo = Conversation(messages)

    @property
    def conversation(self) -> Conversation:
        return self.convo

    @conversation.setter
    def conversation(self, value: Conversation):
        self.convo = value

    def add_user_message(self, user_message: str):
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
        filename = datetime.now().isoformat(timespec="seconds").replace(":", "-")
        self.convo.save(filename)

    @property
    def num_messages(self):
        return len(self.convo)

    def set_convo(self, convo: Conversation):
        self.convo = convo

    def chat_local(self):
        while True:
            message = input("\nUser: ")
            if message == "":
                break
            list(self.respond(message))
        self.save()
