from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Literal, get_args

from teacher.agent.types import Task


RoleType = Literal["user", "system", "assistant"]
ROLES = get_args(RoleType)


@dataclass
class LogEntry:
    """Store one conversation message plus task logging metadata."""

    role: RoleType
    content: str
    task_name: str | None = None
    visible: bool = True
    dynamic_prompts: list[str] = field(default_factory=list)
    input_messages: list[dict[str, str]] = field(default_factory=list)

    @property
    def source(self) -> str:
        """Return the display source for compact logs."""
        return self.task_name or self.role

    def json(self, full=False):
        """Serialize this entry for conversation storage."""
        if not full and not self.task_name and self.visible and not self.dynamic_prompts and not self.input_messages:
            return {"content": self.content, "source": self.role}
        return asdict(self)

    def to_api(self):
        """Convert this entry into chat API message shape."""
        return {"role": self.role, "content": self.content}


class Conversation:
    """Hold ordered conversation entries and serialization helpers."""

    def __init__(self, entries: list[LogEntry] | None = None):
        """Initialize a conversation from optional log entries."""
        entries = entries or []
        assert isinstance(entries, list), f"Expected list[LogEntry], received {type(entries)}"
        self._entries = entries

    def save(self, filename: str):
        """Persist this conversation under data/conversations."""
        os.makedirs("data/conversations", exist_ok=True)
        with open(f"data/conversations/{filename}.json", "w+", encoding="utf-8") as f:
            json.dump(self.json(full=True), f)

    @classmethod
    def load(cls, filepath: str):
        """Load a conversation from a JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            entries = json.load(f)
        return Conversation([cls._load_entry(entry) for entry in entries])

    @staticmethod
    def _load_entry(entry: dict):
        """Load either current or compact legacy log entry shape."""
        if "role" in entry:
            return LogEntry(**entry)
        source = entry["source"]
        role = source if source in ROLES else "system"
        task_name = None if source in ROLES else source
        visible = source in ("user", "assistant")
        return LogEntry(role=role, content=entry["content"], task_name=task_name, visible=visible)

    def append_user(self, content: str):
        """Append a visible user message."""
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
        """Append a model task response with task metadata."""
        self.append_entry(LogEntry(
            role=role,
            content=content,
            task_name=task.name,
            visible=visible,
            dynamic_prompts=dynamic_prompts or [],
            input_messages=input_messages or [],
        ))

    def append_entry(self, entry: LogEntry):
        """Append a raw log entry."""
        self._entries.append(entry)

    def copy(self):
        """Return a shallow copy of this conversation."""
        return Conversation(self._entries.copy())

    def json(self, full=False):
        """Serialize conversation entries."""
        return [m.json(full=full) for m in self._entries]

    def to_api(self):
        """Convert entries to chat API messages."""
        return [m.to_api() for m in self._entries]

    def visible_messages(self):
        """Return the visible user and assistant subset."""
        return Conversation([
            entry for entry in self._entries
            if entry.visible and entry.role in ("user", "assistant")
        ])

    def tail(self, count: int | None):
        """Return the last count entries or the whole conversation."""
        if count is None:
            return self.copy()
        return Conversation(self._entries[-count:])

    def __len__(self):
        """Return the number of log entries."""
        return len(self._entries)

    def __iter__(self):
        """Iterate over log entries."""
        yield from self._entries

    def __getitem__(self, key):
        """Return one entry or a sliced conversation."""
        if isinstance(key, int):
            return self._entries[key]
        return Conversation(self._entries[key])
