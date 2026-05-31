from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, field_validator

from brains.comms.agent_base import ResponseObject


SessionMode = Literal["idle", "question"]


class TopicUpdateResponse(ResponseObject):
    topic_id: str = ""
    intuition: float = 0.0
    details: float = 0.0
    confidence: float = 0.0
    evidence: str = ""

    @field_validator("topic_id", "evidence", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class MemoryUpdateResponse(ResponseObject):
    type: str = "insight"
    topic_id: str = ""
    text: str = ""
    confidence: float = 0.0

    @field_validator("type", "topic_id", "text", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class GraphTopicResponse(ResponseObject):
    topic_id: str = ""
    name: str = ""
    description: str = ""
    confidence: float = 0.0
    evidence: str = ""

    @field_validator("topic_id", "name", "description", "evidence", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class GraphEdgeResponse(ResponseObject):
    topic1: str = ""
    topic2: str = ""
    relation_type: str = "related"
    confidence: float = 0.0
    evidence: str = ""

    @field_validator("topic1", "topic2", "relation_type", "evidence", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class GraphUpdatesResponse(ResponseObject):
    topics: list[GraphTopicResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)


class SessionSummaryResponse(ResponseObject):
    summary: str = ""
    next_step: str = ""

    @field_validator("summary", "next_step", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class SessionTopicUpdatesResponse(ResponseObject):
    topic_updates: list[TopicUpdateResponse] = Field(default_factory=list)


class SessionMemoryExtractionResponse(ResponseObject):
    memories: list[MemoryUpdateResponse] = Field(default_factory=list)


class SessionGraphUpdatesResponse(ResponseObject):
    graph_updates: GraphUpdatesResponse = Field(default_factory=GraphUpdatesResponse)


class SessionFinalizationResponse(ResponseObject):
    summary: str = ""
    next_step: str = ""
    topic_updates: list[TopicUpdateResponse] = Field(default_factory=list)
    memories: list[MemoryUpdateResponse] = Field(default_factory=list)
    graph_updates: GraphUpdatesResponse = Field(default_factory=GraphUpdatesResponse)


class ProfileUpdateGateResponse(ResponseObject):
    accept: bool = False
    reason: str = ""

    @field_validator("reason", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class QuestionTopicResponse(ResponseObject):
    topic_id: str = ""
    name: str = ""
    description: str = ""
    confidence: float = 0.0

    @field_validator("topic_id", "name", "description", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class QuestionTopicResolutionResponse(ResponseObject):
    topics: list[QuestionTopicResponse] = Field(default_factory=list)


class TopicConnectionResponse(ResponseObject):
    topic_id: str = ""
    relation_type: str = "none"
    confidence: float = 0.0
    evidence: str = ""

    @field_validator("topic_id", "relation_type", "evidence", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


class TopicGraphConnectionResponse(ResponseObject):
    connections: list[TopicConnectionResponse] = Field(default_factory=list)


@dataclass
class CommandResult:
    text: str
    should_quit: bool = False


@dataclass
class FinalizationReport:
    summary: str
    next_step: str
    conversation_path: str
    profile_backup_path: str
    audit_id: str
    memories_saved: int = 0
    topics_updated: list[str] = field(default_factory=list)
    topic_update_notes: list[str] = field(default_factory=list)
    graph_changes: int = 0

    def render(self) -> str:
        lines = [
            "Done. I saved this learning session.",
            "",
            f"Today you clarified: {self.summary}",
            f"Next time, we will pick up at: {self.next_step}",
            "",
            f"Conversation: {self.conversation_path}",
            f"Profile backup: {self.profile_backup_path}",
            f"Audit log: {self.audit_id}",
        ]
        if self.topics_updated:
            lines.append(f"Profile topics updated: {', '.join(self.topics_updated)}")
        if self.topic_update_notes:
            lines.append("Why those profile updates:")
            lines.extend(f"- {note}" for note in self.topic_update_notes)
        if self.memories_saved:
            lines.append(f"Memories saved: {self.memories_saved}")
        if self.graph_changes:
            lines.append(f"Topic graph changes: {self.graph_changes}")
        return "\n".join(lines)


HELP_TEXT = """Commands:
/ask <question>          Ask a learning question.
/done                    Finish this session and persist learning updates.
//save                   Save the current conversation without finalizing.
//profile                Show your compact learner profile.
//topic                  Show the current topic context.
//help                   Show this help.
//quit                   Save and exit.
"""
