from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, field_validator, model_validator

from brains.comms.agent_base import ResponseObject
from brains.data.db_vector import MemoryKind


SessionMode = Literal["idle", "question"]
QUESTION_INTENTS = {
    "explain_mechanism",
    "distinguish",
    "apply",
    "debug_model",
    "plan_learning",
}


@dataclass(frozen=True)
class LearnerTopicKnown:
    topic_id: str
    intuition: float
    details: float
    confidence: float

    def render(self) -> str:
        readable = self.topic_id.replace("_", " ")
        return (
            f"{readable}: intuition {self.intuition:.2f}, "
            f"details {self.details:.2f}, confidence {self.confidence:.2f}"
        )


@dataclass(frozen=True)
class LearnerTopicAssumption:
    topic_id: str
    status: str
    reason: str
    confidence: float

    def render(self) -> str:
        readable = self.topic_id.replace("_", " ")
        return f"{readable}: {self.status} ({self.confidence:.2f}) - {self.reason}"


@dataclass(frozen=True)
class QuestionPlan:
    intent: str = "explain_mechanism"
    target_topics: list[str] = field(default_factory=list)
    knowns: list[LearnerTopicKnown] = field(default_factory=list)
    assumptions: list[LearnerTopicAssumption] = field(default_factory=list)
    bottlenecks: list[str] = field(default_factory=list)
    entry_point: str = ""
    teaching_move: str = ""
    avoid: str = ""
    memory_topic_hints: list[str] = field(default_factory=list)

    @property
    def needs_probe(self) -> bool:
        return any(item.status == "needs_probe" for item in self.assumptions)

    def render(self) -> str:
        lines = ["Question plan:"]
        lines.append(f"Intent: {self.intent}")
        lines.append(f"Target topics: {self._render_topics(self.target_topics)}")
        lines.append("Known learner anchors:")
        lines.extend(self._render_items(item.render() for item in self.knowns))
        lines.append("Temporary assumptions:")
        lines.extend(self._render_items(item.render() for item in self.assumptions))
        lines.append(f"Likely bottlenecks: {self._render_topics(self.bottlenecks)}")
        lines.append(f"Recommended entry point: {self.entry_point or 'answer from the learner question directly'}")
        if self.teaching_move:
            lines.append(f"Teaching move: {self.teaching_move}")
        if self.avoid:
            lines.append(f"Avoid: {self.avoid}")
        if self.needs_probe:
            lines.append("Probe guidance: briefly surface the uncertain assumption before committing to a deep path.")
        return "\n".join(lines)

    @staticmethod
    def _render_topics(topics: list[str]) -> str:
        if not topics:
            return "none"
        return ", ".join(topic.replace("_", " ") for topic in topics)

    @staticmethod
    def _render_items(items) -> list[str]:
        rendered = [item for item in items if item]
        return [f"- {item}" for item in rendered] if rendered else ["- none"]


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


class ExtractedMemory(ResponseObject):
    kind: MemoryKind = MemoryKind.INSIGHT
    topic_id: str = ""
    text: str = ""
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def accept_type_alias(cls, data):
        if isinstance(data, dict) and "type" in data and "kind" not in data:
            data = dict(data)
            data["kind"] = data.pop("type")
        return data

    @field_validator("kind", mode="before")
    @classmethod
    def type_to_kind(cls, value):
        if isinstance(value, MemoryKind):
            return value
        if value == "partial_understanding":
            return MemoryKind.PARTIAL_UNDERSTANDING
        for kind in MemoryKind:
            if value in {kind.value, kind.memory_type}:
                return kind
        return value

    @property
    def type(self) -> str:
        return self.kind.memory_type

    def json_data(self):
        data = super().json_data()
        data["type"] = self.kind.memory_type
        del data["kind"]
        return data

    @field_validator("topic_id", "text", mode="before")
    @classmethod
    def none_to_empty_string(cls, value):
        return "" if value is None else value


MemoryUpdateResponse = ExtractedMemory


class MemoryBucketItemResponse(ResponseObject):
    topic_id: str = ""
    text: str = ""
    confidence: float = 0.0

    @field_validator("topic_id", "text", mode="before")
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
    confusions: list[MemoryBucketItemResponse] = Field(default_factory=list)
    partial_understandings: list[MemoryBucketItemResponse] = Field(default_factory=list)
    successful_explanations: list[MemoryBucketItemResponse] = Field(default_factory=list)
    learning_preferences: list[MemoryBucketItemResponse] = Field(default_factory=list)
    insights: list[MemoryBucketItemResponse] = Field(default_factory=list)

    @staticmethod
    def _typed_memories(
        memory_type: MemoryKind,
        memories: list[MemoryBucketItemResponse],
    ) -> list[ExtractedMemory]:
        return [
            ExtractedMemory(
                kind=memory_type,
                topic_id=memory.topic_id,
                text=memory.text,
                confidence=memory.confidence,
            )
            for memory in memories
        ]

    def extracted_memories(self) -> list[ExtractedMemory]:
        return [
            *self._typed_memories(MemoryKind.CONFUSION, self.confusions),
            *self._typed_memories(MemoryKind.PARTIAL_UNDERSTANDING, self.partial_understandings),
            *self._typed_memories(MemoryKind.SUCCESSFUL_EXPLANATION, self.successful_explanations),
            *self._typed_memories(MemoryKind.LEARNING_PREFERENCE, self.learning_preferences),
            *self._typed_memories(MemoryKind.INSIGHT, self.insights),
        ]


class SessionGraphUpdatesResponse(ResponseObject):
    graph_updates: GraphUpdatesResponse = Field(default_factory=GraphUpdatesResponse)


class SessionFinalizationResponse(ResponseObject):
    summary: str = ""
    next_step: str = ""
    topic_updates: list[TopicUpdateResponse] = Field(default_factory=list)
    memories: list[ExtractedMemory] = Field(default_factory=list)
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
    intent: str = "explain_mechanism"
    topics: list[QuestionTopicResponse] = Field(default_factory=list)

    @field_validator("intent", mode="before")
    @classmethod
    def normalize_intent(cls, value):
        intent = "" if value is None else str(value).strip().lower()
        intent = intent.replace("-", "_").replace(" ", "_")
        return intent if intent in QUESTION_INTENTS else "explain_mechanism"


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
