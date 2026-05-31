import json

from teacher.utils.identifiers import normalize_identifier


class TopicGraphStore:
    """Persist and query topic graph nodes, aliases, and edges."""

    @staticmethod
    def create_topic_id(topic: str):
        """Normalize a topic into a graph ID."""
        return normalize_identifier(topic)

    def _aliases_for_topic(self, topic_id: str) -> list[str]:
        """Return aliases for a graph topic."""
        self.cursor.execute("SELECT aliases_json FROM topics WHERE id = ?", (topic_id,))
        row = self.cursor.fetchone()
        if not row:
            return []
        try:
            aliases = json.loads(row["aliases_json"] or "[]")
        except json.JSONDecodeError:
            return []
        return aliases if isinstance(aliases, list) else []

    def resolve_topic_id(self, topic: str | None) -> str:
        """Resolve a topic or alias to a canonical topic ID."""
        topic_id = self.create_topic_id(topic or "")
        if not topic_id:
            return ""
        candidate_ids = [topic_id]
        if topic_id.endswith("ies"):
            candidate_ids.append(f"{topic_id[:-3]}y")
        if topic_id.endswith("s"):
            candidate_ids.append(topic_id[:-1])
        for candidate_id in candidate_ids:
            self.cursor.execute("SELECT id FROM topics WHERE id = ?", (candidate_id,))
            row = self.cursor.fetchone()
            if row:
                return row["id"]
        self.cursor.execute("SELECT id, aliases_json FROM topics")
        for row in self.cursor.fetchall():
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except json.JSONDecodeError:
                aliases = []
            normalized_aliases = {self.create_topic_id(alias) for alias in aliases if alias}
            if topic_id in normalized_aliases:
                return row["id"]
        return topic_id

    def topic_exists(self, topic_id: str) -> bool:
        """Return whether a topic exists."""
        topic_id = self.resolve_topic_id(topic_id)
        if not topic_id:
            return False
        self.cursor.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,))
        return self.cursor.fetchone() is not None

    def get_topic_summaries(self, limit: int = 50) -> list[dict]:
        """Return topic summaries for model context."""
        self.cursor.execute(
            """
            SELECT id, name, description, aliases_json, confidence
            FROM topics
            ORDER BY confidence DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        )
        summaries = []
        for row in self.cursor.fetchall():
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except json.JSONDecodeError:
                aliases = []
            summaries.append(
                {
                    "topic_id": row["id"],
                    "name": row["name"],
                    "description": row["description"] or "",
                    "aliases": aliases if isinstance(aliases, list) else [],
                    "confidence": row["confidence"],
                }
            )
        return summaries

    def connected_targets(self, start_topics: list[str], target_topics: list[str], max_hops: int = 2) -> list[str]:
        """Return target topics reachable from start topics."""
        starts = {self.resolve_topic_id(topic) for topic in start_topics if self.resolve_topic_id(topic)}
        targets = {self.resolve_topic_id(topic) for topic in target_topics if self.resolve_topic_id(topic)}
        if not starts or not targets:
            return []
        found = set(starts & targets)
        frontier = set(starts)
        visited = set(starts)
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            self.cursor.execute(
                f"""
                SELECT topic1, topic2 FROM topic_edges
                WHERE topic1 IN ({placeholders})
                OR topic2 IN ({placeholders})
                """,
                [*frontier, *frontier],
            )
            neighbors = set()
            for row in self.cursor.fetchall():
                neighbors.add(row["topic1"])
                neighbors.add(row["topic2"])
            neighbors -= visited
            found |= neighbors & targets
            visited |= neighbors
            frontier = neighbors
        return [topic for topic in target_topics if self.resolve_topic_id(topic) in found]

    def neighboring_topic_ids(self, topic_ids: list[str], max_hops: int = 1) -> list[str]:
        """Return graph neighbors around topic IDs."""
        starts = [self.resolve_topic_id(topic) for topic in topic_ids if self.resolve_topic_id(topic)]
        if not starts:
            return []
        frontier = set(starts)
        visited = set(starts)
        ordered = []
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            self.cursor.execute(
                f"""
                SELECT topic1, topic2 FROM topic_edges
                WHERE topic1 IN ({placeholders})
                OR topic2 IN ({placeholders})
                """,
                [*frontier, *frontier],
            )
            neighbors = set()
            for row in self.cursor.fetchall():
                neighbors.add(row["topic1"])
                neighbors.add(row["topic2"])
            neighbors -= visited
            for topic_id in sorted(neighbors):
                if topic_id not in ordered:
                    ordered.append(topic_id)
            visited |= neighbors
            frontier = neighbors
        return ordered

    def neighboring_topic_edges(self, topic_ids: list[str]) -> list[dict]:
        """Return edge summaries adjacent to topic IDs."""
        starts = [self.resolve_topic_id(topic) for topic in topic_ids if self.resolve_topic_id(topic)]
        if not starts:
            return []
        placeholders = ",".join("?" for _ in starts)
        self.cursor.execute(
            f"""
            SELECT topic1, topic2, relation_type, confidence
            FROM topic_edges
            WHERE topic1 IN ({placeholders})
            OR topic2 IN ({placeholders})
            """,
            [*starts, *starts],
        )
        start_set = set(starts)
        edges = []
        seen = set()
        for row in self.cursor.fetchall():
            topic1 = row["topic1"]
            topic2 = row["topic2"]
            if topic1 in start_set and topic2 in start_set:
                continue
            neighbor = topic2 if topic1 in start_set else topic1
            key = (neighbor, row["relation_type"])
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "topic_id": neighbor,
                    "relation_type": row["relation_type"],
                    "confidence": float(row["confidence"] or 0.0),
                }
            )
        return edges

    def merge_topics(self, source_id: str, target_id: str) -> bool:
        """Merge one topic into another topic."""
        source_raw = str(source_id or "")
        source_resolved = self.resolve_topic_id(source_raw)
        target_id = self.resolve_topic_id(target_id)
        self.cursor.execute("SELECT * FROM topics WHERE id = ?", (source_raw,))
        exact_source = self.cursor.fetchone()
        source_id = source_raw if exact_source and source_raw != target_id else source_resolved
        if not source_id or not target_id or source_id == target_id:
            return False
        self.cursor.execute("SELECT * FROM topics WHERE id = ?", (source_id,))
        source = self.cursor.fetchone()
        if not source:
            return False
        self.upsert_topic(
            target_id,
            aliases=[source_id, source["name"], *self._aliases_for_topic(source_id)],
            description=source["description"],
            confidence=float(source["confidence"] or 0.5),
        )
        for column in ("topic1", "topic2"):
            self.cursor.execute(f"SELECT * FROM topic_edges WHERE {column} = ?", (source_id,))
            for edge in self.cursor.fetchall():
                topic1 = target_id if edge["topic1"] == source_id else edge["topic1"]
                topic2 = target_id if edge["topic2"] == source_id else edge["topic2"]
                if topic1 != topic2:
                    self.upsert_topic_edge(
                        topic1,
                        topic2,
                        edge["relation_type"],
                        confidence=float(edge["confidence"] or 0.5),
                        evidence=edge["evidence"],
                        session_id=edge["created_from_session_id"],
                    )
        self.cursor.execute("UPDATE OR IGNORE topic_context SET topic_id = ? WHERE topic_id = ?", (target_id, source_id))
        self.cursor.execute("UPDATE OR IGNORE mastery_history SET topic_id = ? WHERE topic_id = ?", (target_id, source_id))
        self.cursor.execute("DELETE FROM topic_context WHERE topic_id = ?", (source_id,))
        self.cursor.execute("DELETE FROM mastery_history WHERE topic_id = ?", (source_id,))
        self.cursor.execute("DELETE FROM topic_edges WHERE topic1 = ? OR topic2 = ?", (source_id, source_id))
        self.cursor.execute("DELETE FROM topics WHERE id = ?", (source_id,))
        self.conn.commit()
        return True

    def upsert_topic(
        self,
        topic_id: str,
        name: str | None = None,
        description: str | None = None,
        aliases: list[str] | None = None,
        created_from: str | None = None,
        confidence: float = 0.5,
    ):
        """Insert or update a topic graph node."""
        original_id = self.create_topic_id(topic_id)
        if not original_id:
            return ""
        topic_id = self.resolve_topic_id(original_id)
        name = name or topic_id.replace("_", " ").title()
        existing_aliases = self._aliases_for_topic(topic_id)
        merged_aliases = sorted({
            self.create_topic_id(alias)
            for alias in [original_id, *(aliases or [])]
            if self.create_topic_id(alias) and self.create_topic_id(alias) != topic_id
        } | set(existing_aliases))
        aliases_json = self._json(merged_aliases)
        self.cursor.execute(
            """
            INSERT INTO topics (id, name, description, aliases_json, created_from, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=COALESCE(excluded.name, topics.name),
                description=COALESCE(excluded.description, topics.description),
                aliases_json=CASE
                    WHEN excluded.aliases_json != '[]' THEN excluded.aliases_json
                    ELSE topics.aliases_json
                END,
                confidence=MAX(COALESCE(topics.confidence, 0), COALESCE(excluded.confidence, 0))
            """,
            (topic_id, name, description, aliases_json, created_from, confidence),
        )
        self.conn.commit()
        return topic_id

    def upsert_topic_edge(
        self,
        topic1: str,
        topic2: str,
        relation_type: str,
        confidence: float = 0.5,
        evidence: str | None = None,
        session_id: str | None = None,
    ):
        """Insert or update a topic graph edge."""
        topic1 = self.upsert_topic(topic1)
        topic2 = self.upsert_topic(topic2)
        relation_type = self.create_topic_id(relation_type)
        if not topic1 or not topic2 or topic1 == topic2:
            return False
        confidence = max(0.0, min(1.0, float(confidence)))
        self.cursor.execute(
            """
            INSERT INTO topic_edges
                (topic1, topic2, relation_type, confidence, evidence, created_from_session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic1, topic2, relation_type) DO UPDATE SET
                confidence=MAX(COALESCE(topic_edges.confidence, 0), excluded.confidence),
                evidence=COALESCE(excluded.evidence, topic_edges.evidence),
                created_from_session_id=COALESCE(excluded.created_from_session_id, topic_edges.created_from_session_id)
            """,
            (topic1, topic2, relation_type, confidence, evidence, session_id),
        )
        self.conn.commit()
        return True

    def connect_topic_to_session(self, session_id: str, topics: list[str]):
        """Connect topics to a legacy session context row."""
        for topic in topics:
            topic_id = self.upsert_topic(topic, name=topic)
            self.cursor.execute(
                "INSERT OR IGNORE INTO topic_context (topic_id, context_type, context_id) VALUES (?, ?, ?)",
                (topic_id, "session_start", session_id)
            )
        self.conn.commit()
