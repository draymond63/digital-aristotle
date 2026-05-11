from dataclasses import dataclass, asdict, field
from pathlib import Path
from yaml import safe_load, safe_dump
from datetime import datetime
from typing import Optional


@dataclass
class Domain:
    intuition: float = 0
    details: float = 0
    confidence: float = 0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat(timespec="hours"))


@dataclass
class Profile:
    filepath: Path
    domains: dict[str, Domain] = field(default_factory=dict)
    preferences: dict[str, list[str]] = field(default_factory=dict)
    dislikes: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    current_topics: list[str] = field(default_factory=list)

    @property
    def current_topic(self) -> Optional[str]:
        return self.current_topics[-1] if self.current_topics else None

    def save(self):
        safe_dump(asdict(self), open(self.filepath, "w"))

    @classmethod
    def load_user(cls, username: str):
        filepath = Path(f"data/profiles/{username}.yaml")
        if not filepath.exists():
            profile = cls(filepath=filepath)
            return profile
        return cls.load(filepath)

    @classmethod
    def load(cls, filepath: str | Path):
        if not isinstance(filepath, Path):
            filepath = Path(filepath)
        data = safe_load(open(filepath, "r"))
        domains = {name: Domain(**details) for name, details in data.get("domains", {}).items()}
        preferences = data.get("preferences", {})
        dislikes = data.get("dislikes", [])
        interests = data.get("interests", [])
        return cls(filepath=filepath, domains=domains, preferences=preferences, dislikes=dislikes, interests=interests)
    
    def __str__(self):
        d = asdict(self)
        d.pop("filepath")
        return safe_dump(d, sort_keys=False)

    def update_domain(self, domain_name: str, **kwargs):
        domain = self.domains.get(domain_name, Domain(name=domain_name))
        for key, value in kwargs.items():
            setattr(domain, key, value)
        domain.last_updated = datetime.now().isoformat(timespec="hours")
        self.domains[domain_name] = domain
        self.save()

    def update_preferences(self, category: str, item: str):
        if category not in self.preferences:
            self.preferences[category] = []
        if item not in self.preferences[category]:
            self.preferences[category].append(item)
            self.save()
    
    def update_dislikes(self, item: str):
        if item not in self.dislikes:
            self.dislikes.append(item)
            self.save()
    
    def update_interests(self, item: str):
        if item not in self.interests:
            self.interests.append(item)
            self.save()
