from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SessionMode = Literal["idle", "goal_intake", "goal_confirm", "syllabus_review", "goal", "question"]


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
    milestone_status: str = "continue"
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
        if self.milestone_status == "continue":
            lines.append("Milestone status: continuing this milestone next time")
        elif self.milestone_status == "done":
            lines.append("Milestone status: ready for the next milestone")
        if self.topic_update_notes:
            lines.append("Why those profile updates:")
            lines.extend(f"- {note}" for note in self.topic_update_notes)
        if self.memories_saved:
            lines.append(f"Memories saved: {self.memories_saved}")
        if self.graph_changes:
            lines.append(f"Topic graph changes: {self.graph_changes}")
        return "\n".join(lines)


HELP_TEXT = """Commands:
/goal <topic or outcome>  Start a resumable learning goal.
/learn <topic or outcome> Same as /goal.
/continue                Resume your most recent active goal.
/goals                   Show active goals.
/ask <question>          Ask a one-off question without creating a goal.
/done                    Finish this session and persist learning updates.
/save                    Save the current conversation without finalizing.
/profile                 Show your compact learner profile.
/topic                   Show the current topic or goal context.
/new                     Save this conversation and start fresh.
/help                    Show this help.
/quit                    Save and exit.
"""
