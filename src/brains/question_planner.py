from __future__ import annotations

from brains.data.db_sql import SQLDatabase
from brains.data.profile import Profile
from brains.session_types import LearnerTopicAssumption, LearnerTopicKnown, QuestionPlan


class QuestionPlanner:
    BOTTLENECK_RELATIONS = {"prerequisite", "enables"}
    INTENT_GUIDANCE = {
        "explain_mechanism": (
            "explain the causal or operational mechanism that makes the result happen",
            "stopping at labels, definitions, or surface-level examples",
        ),
        "distinguish": (
            "contrast the nearby concepts using the same example from both sides",
            "broad prerequisite review unless the distinction depends on it",
        ),
        "apply": (
            "start from the concrete case and use the abstract concept as the scaffold",
            "re-teaching the abstraction before applying it",
        ),
        "debug_model": (
            "state the learner's current model, preserve the useful part, then repair the failing edge",
            "discarding the learner's model and restarting from a generic explanation",
        ),
        "plan_learning": (
            "turn the target into a short learning path with prerequisites, sequence, and first lesson",
            "answering only the first concept without a path",
        ),
    }

    def __init__(self, sql_db: SQLDatabase, profile: Profile):
        self.sql_db = sql_db
        self.profile = profile

    def build(self, target_topics: list[str], profile_topic_hints: list[str], intent: str = "explain_mechanism") -> QuestionPlan:
        intent = self._normalize_intent(intent)
        connected_profile_topics = self.sql_db.connected_targets(target_topics, profile_topic_hints, max_hops=2)
        direct_known_topics = [
            matched
            for topic_id in target_topics
            for matched in [self._matching_profile_topic(topic_id)]
            if matched
        ]
        matched_neighbor_topics = [
            matched
            for edge in self.sql_db.neighboring_topic_edges(target_topics)
            for matched in [self._matching_profile_topic(edge["topic_id"])]
            if matched
        ]
        known_topic_ids = self._dedupe_topics([*direct_known_topics, *connected_profile_topics, *matched_neighbor_topics])
        knowns = [self._known_from_profile(topic_id) for topic_id in known_topic_ids]
        assumptions = [self._assumption_from_known(topic) for topic in knowns]
        gap_assumptions = self._gap_assumptions(target_topics, intent)
        assumptions.extend(gap_assumptions)
        bottlenecks = [item.topic_id for item in gap_assumptions if item.status == "needs_probe"][:4]
        anchors = self._rank_anchors(target_topics, knowns)
        teaching_move, avoid = self.INTENT_GUIDANCE[intent]
        return QuestionPlan(
            intent=intent,
            target_topics=target_topics,
            knowns=knowns,
            assumptions=assumptions,
            bottlenecks=bottlenecks,
            entry_point=self._entry_point(intent, target_topics, anchors, bottlenecks),
            teaching_move=teaching_move,
            avoid=avoid,
            memory_topic_hints=anchors,
        )

    def _known_from_profile(self, topic_id: str) -> LearnerTopicKnown:
        resolved = self.sql_db.resolve_topic_id(topic_id)
        state = self.profile.topics[resolved]
        return LearnerTopicKnown(
            topic_id=resolved,
            intuition=float(state.intuition),
            details=float(state.details),
            confidence=float(state.confidence),
        )

    @staticmethod
    def _assumption_from_known(topic: LearnerTopicKnown) -> LearnerTopicAssumption:
        score = (topic.intuition + topic.details + topic.confidence) / 3
        if score >= 0.65:
            status = "safe_to_assume"
        elif score >= 0.35:
            status = "likely_known"
        else:
            status = "needs_probe"
        return LearnerTopicAssumption(
            topic_id=topic.topic_id,
            status=status,
            confidence=score,
            reason="profile evidence connects this topic to the current question",
        )

    def _gap_assumptions(self, target_topics: list[str], intent: str) -> list[LearnerTopicAssumption]:
        target_set = {self.sql_db.resolve_topic_id(topic_id) for topic_id in target_topics}
        assumptions = []
        for edge in self.sql_db.neighboring_topic_edges(target_topics):
            topic_id = self.sql_db.resolve_topic_id(edge["topic_id"])
            if not topic_id or topic_id in target_set or self._matching_profile_topic(topic_id):
                continue
            relation = edge["relation_type"]
            if relation in self.BOTTLENECK_RELATIONS and intent in {"explain_mechanism", "plan_learning"}:
                status = "needs_probe"
                reason = f"{relation} relation near the target topic, but not present in the learner profile"
            else:
                status = "possible_gap"
                reason = f"{relation} relation near the target topic, but not present in the learner profile"
            assumptions.append(
                LearnerTopicAssumption(
                    topic_id=topic_id,
                    status=status,
                    confidence=0.35,
                    reason=reason,
                )
            )
        return assumptions[:4]

    def _normalize_intent(self, intent: str) -> str:
        intent = str(intent or "").strip().lower().replace("-", "_").replace(" ", "_")
        return intent if intent in self.INTENT_GUIDANCE else "explain_mechanism"

    def _rank_anchors(self, target_topics: list[str], knowns: list[LearnerTopicKnown]) -> list[str]:
        target_set = {self.sql_db.resolve_topic_id(topic_id) for topic_id in target_topics}
        strong_or_likely_targets = [
            topic.topic_id
            for topic in knowns
            if topic.topic_id in target_set and self._topic_score(topic) >= 0.35
        ]
        non_target_anchors = [topic.topic_id for topic in knowns if topic.topic_id not in target_set]
        return [*strong_or_likely_targets, *non_target_anchors] or [topic.topic_id for topic in knowns]

    @staticmethod
    def _dedupe_topics(topic_ids: list[str]) -> list[str]:
        deduped = []
        for topic_id in topic_ids:
            if topic_id and topic_id not in deduped:
                deduped.append(topic_id)
        return deduped

    def _matching_profile_topic(self, topic_id: str) -> str:
        resolved = self.sql_db.resolve_topic_id(topic_id)
        if resolved in self.profile.topics:
            return resolved
        topic_tokens = self._topic_tokens(resolved)
        if len(topic_tokens) < 2:
            return ""
        for profile_topic_id in self.profile.topics:
            profile_tokens = self._topic_tokens(profile_topic_id)
            if self._tokens_contain(profile_tokens, topic_tokens):
                return profile_topic_id
        return ""

    @staticmethod
    def _entry_point(intent: str, target_topics: list[str], anchors: list[str], bottlenecks: list[str]) -> str:
        target_id = target_topics[0] if target_topics else ""
        target = target_id.replace("_", " ") if target_id else "the learner's question"
        anchor = ""
        for anchor_id in anchors:
            if anchor_id != target_id:
                anchor = anchor_id.replace("_", " ")
                break
        if intent == "explain_mechanism":
            return f"explain why {target} works, using {anchor} as the anchor" if anchor else f"explain why {target} works"
        if intent == "distinguish":
            return f"contrast {target} against the concept the learner is mixing it with"
        if intent == "apply":
            return f"apply {target} to the learner's concrete case before broadening the abstraction"
        if intent == "debug_model":
            return f"repair the learner's mental model of {target} without restarting from scratch"
        if intent == "plan_learning":
            return f"build a short path into {target}, starting with the first prerequisite gap" if bottlenecks else f"build a short path into {target}"
        if anchors:
            anchor_id = anchors[0]
            if anchor_id == target_id:
                return f"continue from the learner's existing understanding of {target} and sharpen the specific distinction they asked about"
            return f"explain {target} by connecting it to the learner's existing anchor in {anchor_id.replace('_', ' ')}"
        if bottlenecks:
            bottleneck = bottlenecks[0].replace("_", " ")
            return f"answer {target} directly, but define {bottleneck} if it becomes necessary"
        return f"answer {target} directly from the learner's wording"

    @staticmethod
    def _topic_score(topic: LearnerTopicKnown) -> float:
        return (topic.intuition + topic.details + topic.confidence) / 3

    @staticmethod
    def _topic_tokens(topic_id: str) -> list[str]:
        return [item for item in topic_id.split("_") if item]

    @staticmethod
    def _tokens_contain(container: list[str], contained: list[str]) -> bool:
        if len(contained) > len(container):
            return False
        for index in range(len(container) - len(contained) + 1):
            if container[index:index + len(contained)] == contained:
                return True
        return False
