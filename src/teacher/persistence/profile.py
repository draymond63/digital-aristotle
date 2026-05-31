from dataclasses import dataclass, asdict, field
from pathlib import Path
from yaml import safe_load, safe_dump
from datetime import datetime
import shutil

from teacher.utils.identifiers import normalize_identifier, normalize_list


@dataclass
class TopicState:
    """Store compact durable mastery state for one topic."""

    intuition: float = 0
    details: float = 0
    confidence: float = 0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat(timespec="hours"))


@dataclass
class Profile:
    """Store the compact durable learner profile."""

    filepath: Path
    background: dict[str, str | list[str]] = field(default_factory=dict)
    topics: dict[str, TopicState] = field(default_factory=dict)
    preferences: dict[str, list[str]] = field(default_factory=dict)
    interests: list[str] = field(default_factory=list)
    current_topics: list[str] = field(default_factory=list)

    def save(self):
        """Write the profile YAML file."""
        data = self.to_dict()
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            safe_dump(data, f, sort_keys=False)

    def backup(self, backup_root: str | Path = "data/profile_backups") -> Path:
        """Copy or synthesize a profile backup file."""
        backup_root = Path(backup_root)
        username = self.filepath.stem
        backup_dir = backup_root / username
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds").replace(":", "-")
        backup_path = backup_dir / f"{timestamp}.yaml"
        if self.filepath.exists():
            shutil.copy2(self.filepath, backup_path)
        else:
            with open(backup_path, "w", encoding="utf-8") as f:
                safe_dump(self.to_dict(), f, sort_keys=False)
        return backup_path

    @classmethod
    def load_user(cls, username: str):
        """Load a profile by username from the runtime profile directory."""
        filepath = Path(f"data/profiles/{username}.yaml")
        if not filepath.exists():
            profile = cls(filepath=filepath)
            return profile
        return cls.load(filepath)

    @classmethod
    def load(cls, filepath: str | Path):
        """Load a profile from a YAML path."""
        if not isinstance(filepath, Path):
            filepath = Path(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = safe_load(f) or {}
        topic_data = data.get("topics", {})
        background = {}
        for key, value in data.get("background", {}).items():
            key = normalize_identifier(key)
            if isinstance(value, list):
                background[key] = normalize_list(value)
            elif isinstance(value, str):
                background[key] = normalize_identifier(value)

        topics = {}
        for name, details in topic_data.items():
            topic_id = normalize_identifier(name)
            if topic_id:
                topics[topic_id] = TopicState(**details)
        preferences = {
            normalize_identifier(category): normalize_list(items)
            for category, items in data.get("preferences", {}).items()
        }
        interests = normalize_list(data.get("interests", []))
        current_topics = normalize_list(data.get("current_topics", []))
        return cls(
            filepath=filepath,
            background=background,
            topics=topics,
            preferences=preferences,
            interests=interests,
            current_topics=current_topics,
        )
    
    def __str__(self):
        """Render the profile as YAML."""
        return safe_dump(self.to_dict(), sort_keys=False)

    def to_dict(self):
        """Return normalized profile data for YAML persistence."""
        return {
            "background": {
                normalize_identifier(key): normalize_list(value) if isinstance(value, list) else normalize_identifier(value)
                for key, value in self.background.items()
                if normalize_identifier(key)
            },
            "topics": {
                normalize_identifier(topic_id): asdict(topic)
                for topic_id, topic in self.topics.items()
                if normalize_identifier(topic_id)
            },
            "preferences": {
                normalize_identifier(category): normalize_list(items)
                for category, items in self.preferences.items()
            },
            "interests": normalize_list(self.interests),
            "current_topics": normalize_list(self.current_topics),
        }

    def update_topic(self, topic_id: str, **kwargs):
        """Update compact mastery values for one topic."""
        topic_id = normalize_identifier(topic_id)
        topic = self.topics.get(topic_id, TopicState())
        for key, value in kwargs.items():
            if key in {"intuition", "details", "confidence"}:
                value = max(0.0, min(1.0, float(value)))
            setattr(topic, key, value)
        topic.last_updated = datetime.now().isoformat(timespec="hours")
        self.topics[topic_id] = topic
        self.save()

    def update_background(self, category: str, value: str | list[str]):
        """Update one background category."""
        category = normalize_identifier(category)
        if not category:
            return

        if isinstance(value, list):
            existing = self.background.get(category, [])
            if not isinstance(existing, list):
                existing = [existing]
            self.background[category] = normalize_list(existing + value)
        else:
            self.background[category] = normalize_identifier(value)
        self.save()

    def update_preferences(self, category: str, item: str):
        """Add one normalized preference item."""
        category = normalize_identifier(category)
        item = normalize_identifier(item)
        if category not in self.preferences:
            self.preferences[category] = []
        if item and item not in self.preferences[category]:
            self.preferences[category].append(item)
            self.save()
    
    def update_interests(self, item: str):
        """Add one normalized interest."""
        item = normalize_identifier(item)
        if item not in self.interests:
            self.interests.append(item)
            self.save()

    def add_current_topic(self, topic_id: str):
        """Add a normalized current topic."""
        topic_id = normalize_identifier(topic_id)
        if topic_id and topic_id not in self.current_topics:
            self.current_topics.append(topic_id)
            self.save()
