from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field

from brains.comms.agent_base import ResponseObject


SessionMode = Literal["idle", "question"]


class TopicUpdateResponse(ResponseObject):
    topic_id: str = ""
    intuition: float = 0.0
    details: float = 0.0
    confidence: float = 0.0
    evidence: str = ""


class MemoryUpdateResponse(ResponseObject):
    type: str = "insight"
    topic_id: str = ""
    text: str = ""
    confidence: float = 0.0


class GraphTopicResponse(ResponseObject):
    topic_id: str = ""
    name: str = ""
    description: str = ""
    confidence: float = 0.0
    evidence: str = ""


class GraphEdgeResponse(ResponseObject):
    topic1: str = ""
    topic2: str = ""
    relation_type: str = "related"
    confidence: float = 0.0
    evidence: str = ""


class GraphUpdatesResponse(ResponseObject):
    topics: list[GraphTopicResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)


class SessionFinalizationResponse(ResponseObject):
    summary: str = ""
    next_step: str = ""
    topic_updates: list[TopicUpdateResponse] = Field(default_factory=list)
    memories: list[MemoryUpdateResponse] = Field(default_factory=list)
    graph_updates: GraphUpdatesResponse = Field(default_factory=GraphUpdatesResponse)


class ProfileUpdateGateResponse(ResponseObject):
    accept: bool = False
    reason: str = ""


class QuestionTopicResponse(ResponseObject):
    topic_id: str = ""
    name: str = ""
    description: str = ""
    confidence: float = 0.0


class QuestionTopicResolutionResponse(ResponseObject):
    topics: list[QuestionTopicResponse] = Field(default_factory=list)


class TopicConnectionResponse(ResponseObject):
    topic_id: str = ""
    relation_type: str = "none"
    confidence: float = 0.0
    evidence: str = ""


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
//new                    Save this conversation and start fresh.
//help                   Show this help.
//quit                   Save and exit.
"""
