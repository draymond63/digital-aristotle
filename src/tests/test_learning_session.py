from pathlib import Path
from tempfile import TemporaryDirectory
import os

from brains.data.db_sql import SQLDatabase
from brains.data.profile import Profile
from brains.comms.prompts_session import (
    PROFILE_UPDATE_GATE_PROMPT,
    QUESTION_TOPIC_RESOLUTION_PROMPT,
    SESSION_MEMORY_EXTRACTION_PROMPT,
    SESSION_TOPIC_UPDATES_PROMPT,
    TOPIC_GRAPH_CONNECTION_PROMPT,
)
from brains.session import LearningSession
from brains.session_types import (
    GraphEdgeResponse,
    GraphTopicResponse,
    GraphUpdatesResponse,
    MemoryUpdateResponse,
    SessionMemoryExtractionResponse,
    TopicUpdateResponse,
)


class FakeVectorDB:
    def __init__(self):
        self.added = []
        self.asks = []
        self.queries = []
        self.previous_ask_queries = []

    def log_ask(self, msg, session_id, user_id=None):
        self.asks.append((msg, session_id, user_id))

    def query_pretty(self, *args, **kwargs):
        self.queries.append((args, kwargs))
        return ""

    def find_asks(self, query, max_dist=0.5, user_id=None):
        self.previous_ask_queries.append((query, max_dist, user_id))
        return ["what is covariance?"]

    def add(self, collection_name, ids, documents, metadatas=None):
        self.added.append((collection_name, ids, documents, metadatas))


class FakeAgent:
    def __init__(self):
        self.finalized = False
        self.profile_gate_accept = True
        self.profile_gate_packets = []
        self.topic_update_packets = []
        self.question_topic_packets = []
        self.topic_connection_packets = []
        self.graph_update_packets = []

    def run_task_json(self, task, conversation, dynamic_prompts=None, packet=None):
        if task.name == "session_summary":
            self.finalized = True
            return task.output_format.model_validate({
                "summary": "prediction/correction and uncertainty became clearer",
                "next_step": "connect covariance to position and velocity",
            })
        if task.name == "session_topic_updates":
            self.finalized = True
            self.topic_update_packets.append("\n".join(dynamic_prompts or []))
            return task.output_format.model_validate({
                "topic_updates": [
                    {
                        "topic_id": "kalman_filter",
                        "intuition": 0.4,
                        "details": 0.1,
                        "confidence": 0.5,
                        "evidence": "The learner paraphrased prediction and correction.",
                    }
                ],
            })
        if task.name == "session_memory_extraction":
            self.finalized = True
            return task.output_format.model_validate({
                "insights": [
                    {
                        "topic_id": "kalman_filter",
                        "text": "Learner framed Kalman filtering as prediction then correction.",
                        "confidence": 0.8,
                    }
                ],
                "successful_explanations": [
                    {
                        "topic_id": "kalman_filter",
                        "text": "Prediction-then-correction framing helped the learner understand Kalman filters.",
                        "confidence": 0.8,
                    }
                ],
            })
        if task.name == "session_graph_updates":
            self.finalized = True
            self.graph_update_packets.append("\n".join(dynamic_prompts or []))
            return task.output_format.model_validate({
                "graph_updates": {
                    "topics": [
                        {
                            "topic_id": "kalman_filter",
                            "name": "Kalman Filter",
                            "description": "Recursive estimator for noisy dynamic systems.",
                            "confidence": 0.8,
                            "evidence": "Session discussed Kalman filters.",
                        }
                    ],
                    "edges": [
                        {
                            "topic1": "covariance",
                            "topic2": "kalman_filter",
                            "relation_type": "prerequisite",
                            "confidence": 0.7,
                            "evidence": "The session discussed covariance as uncertainty tracking.",
                        }
                    ],
                },
            })
        if task.name == "profile_update_gate":
            self.profile_gate_packets.append("\n".join(dynamic_prompts or []))
            return task.output_format.model_validate({
                "accept": self.profile_gate_accept,
                "reason": (
                    "The learner paraphrased prediction and correction."
                    if self.profile_gate_accept
                    else "The transcript does not support the proposed update."
                ),
            })
        if task.name == "question_topic_resolver":
            context = "\n".join(dynamic_prompts or [])
            user_text = "\n".join(message.content for message in conversation.visible_messages())
            self.question_topic_packets.append(f"{context}\n{user_text}")
            if "widest direction" in user_text.lower():
                return task.output_format.model_validate({
                    "topics": [
                        {
                            "topic_id": "pca_variance_maximization",
                            "name": "PCA Variance Maximization",
                            "description": "Why PCA preserves directions with the most variance.",
                            "confidence": 0.9,
                        }
                    ]
                })
            if "http etag" in user_text.lower():
                return task.output_format.model_validate({
                    "topics": [
                        {
                            "topic_id": "http_cache_validation",
                            "name": "HTTP Cache Validation",
                            "description": "How validators such as ETags avoid unnecessary transfer.",
                            "confidence": 0.9,
                        }
                    ]
                })
            return task.output_format.model_validate({
                "topics": [{"topic_id": "covariance", "name": "Covariance", "description": "", "confidence": 0.9}]
            })
        if task.name == "topic_graph_connection":
            context = "\n".join(dynamic_prompts or [])
            user_text = "\n".join(message.content for message in conversation.visible_messages())
            self.topic_connection_packets.append(f"{context}\n{user_text}")
            if "pca_variance_maximization" in user_text and "pca_eigenvectors_variance" in context:
                return task.output_format.model_validate({
                    "connections": [
                        {
                            "topic_id": "pca_eigenvectors_variance",
                            "relation_type": "related",
                            "confidence": 0.86,
                            "evidence": "Both topics concern PCA variance directions.",
                        }
                    ]
                })
            return task.output_format.model_validate({"connections": []})
        raise AssertionError(f"Unexpected JSON task: {task.name}")

    def run_task(self, task, conversation, dynamic_prompts=None, packet=None):
        if task.name == "teacher":
            return "A Kalman filter alternates prediction and correction."
        raise AssertionError(f"Unexpected text task: {task.name}")

    def stream_task(self, task, conversation, dynamic_prompts=None, packet=None):
        yield self.run_task(task, conversation, dynamic_prompts, packet)

    def build_task_messages(self, task, conversation, dynamic_prompts=None, packet=None):
        return [{"role": "system", "content": task.static_prompt}]


def make_session(tmpdir: Path):
    os.chdir(tmpdir)
    (tmpdir / "data" / "profiles").mkdir(parents=True)
    profile = Profile.load_user("tester")
    db = SQLDatabase(tmpdir / "data" / "test.db")
    return LearningSession(
        user_id="tester",
        sql_db=db,
        vector_db=FakeVectorDB(),
        profile=profile,
        agent=FakeAgent(),
    )


def test_schema_is_idempotent():
    with TemporaryDirectory() as dirname:
        path = Path(dirname) / "data" / "test.db"
        SQLDatabase(path).close()
        SQLDatabase(path).close()
        db = SQLDatabase(path)
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_sessions'")
        assert db.cursor.fetchone() is not None
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='semantic_memories'")
        assert db.cursor.fetchone() is not None
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        removed_table = "learning_" + "go" + "als"
        assert removed_table not in {row["name"] for row in db.cursor.fetchall()}
        db.close()


def test_find_learning_session_by_conversation_path():
    with TemporaryDirectory() as dirname:
        db = SQLDatabase(Path(dirname) / "data" / "test.db")
        session_id = db.create_learning_session("tester", "question")
        db.finish_learning_session(session_id, conversation_path="data/conversations/example.json")
        assert db.find_learning_session_by_conversation("tester", "data/conversations/example.json") == session_id
        assert db.find_learning_session_by_conversation("other", "data/conversations/example.json") is None
        db.close()


def test_semantic_memories_can_be_marked_replaced():
    with TemporaryDirectory() as dirname:
        db = SQLDatabase(Path(dirname) / "data" / "test.db")
        session_id = db.create_learning_session("tester", "question")
        memory_id = db.insert_semantic_memory(
            user_id="tester",
            session_id=session_id,
            collection="insights",
            topic_id="confidence_interval",
            text="Learner understands coverage.",
            extraction_prompt_version="test",
        )
        assert db.live_semantic_memory_ids("tester", session_id) == [memory_id]
        assert db.mark_semantic_memories_replaced("tester", session_id) == 1
        assert db.live_semantic_memory_ids("tester", session_id) == []
        db.close()


def test_question_session_lifecycle_and_finalization():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            response = session.handle("/ask what is covariance?")
            assert "prediction and correction" in response.text.lower()
            assert session.vector_db.asks[0][2] == "tester"
            queried_collections = {kwargs["collection_name"] for _, kwargs in session.vector_db.queries}
            assert queried_collections == {
                "insights",
                "confusions",
                "partial_understandings",
                "successful_explanations",
                "learning_preferences",
            }
            assert all(kwargs["user_id"] == "tester" for _, kwargs in session.vector_db.queries)
            assert session.vector_db.previous_ask_queries[0][2] == "tester"
            assert session.mode == "question"
            session.sql_db.cursor.execute(
                "SELECT status, conversation_path FROM learning_sessions WHERE id = ?",
                (session.active_session_id,),
            )
            row = session.sql_db.cursor.fetchone()
            assert row["status"] == "active"
            assert row["conversation_path"]

            report = session.handle("/done").text
            assert "Today you clarified: prediction/correction and uncertainty became clearer" in report
            assert "Profile backup:" in report
            assert "Audit log:" in report
            assert "kalman_filter" in session.profile.topics
            assert session.vector_db.added
            assert session.vector_db.added[0][3][0]["user_id"] == "tester"
            assert session.vector_db.added[0][3][0]["topic_id"] == "kalman_filter"
            saved_collections = [item[0] for item in session.vector_db.added]
            assert "insights" in saved_collections
            assert "successful_explanations" in saved_collections
            session.sql_db.cursor.execute("SELECT id, collection, text FROM semantic_memories WHERE user_id = ?", ("tester",))
            rows = session.sql_db.cursor.fetchall()
            assert len(rows) == len(session.vector_db.added)
            assert {row["id"] for row in rows} == {item[1][0] for item in session.vector_db.added}
            assert session.mode == "idle"
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_bare_message_starts_question_session():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            response = session.handle("what is covariance?")
            assert "prediction and correction" in response.text.lower()
            assert session.mode == "question"
            assert session.active_session_id
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_question_context_steers_away_from_generic_overview():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            context = session._build_question_context(
                "I have a mental model but I am fuzzy on the distinction."
            )
            assert "Use the learner's own wording as the starting point" in context
            assert "sharpen that model" in context
            assert "use them to continue the prior line of reasoning" in context
            assert "Avoid broad comparison lists" in context
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_question_memory_query_uses_graph_connected_profile_topics():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.profile.update_topic("pca_eigenvectors_variance", intuition=0.25, details=0.25, confidence=0.25)
            session.sql_db.upsert_topic(
                "pca_eigenvectors_variance",
                name="PCA Eigenvectors and Variance",
                description="How PCA eigenvectors relate to maximal variance directions.",
            )
            session.handle("/ask Why does the widest direction preserve information?")
            insight_query = next(
                kwargs["query_texts"]
                for _, kwargs in session.vector_db.queries
                if kwargs["collection_name"] == "insights"
            )
            assert "Why does the widest direction preserve information?" in insight_query
            assert "pca eigenvectors variance" in insight_query
            assert any("Related learner topic: pca eigenvectors variance" in item for item in insight_query)
            assert session.agent.question_topic_packets
            assert session.agent.topic_connection_packets
            assert session.sql_db.connected_targets(
                ["pca_variance_maximization"],
                ["pca_eigenvectors_variance"],
                max_hops=2,
            ) == ["pca_eigenvectors_variance"]
            assert session.sql_db.topic_exists("pca_variance_maximization")
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_unrelated_question_does_not_use_profile_topic_memory_hint():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.profile.update_topic("pca_eigenvectors_variance", intuition=0.25, details=0.25, confidence=0.25)
            session.sql_db.upsert_topic(
                "pca_eigenvectors_variance",
                name="PCA Eigenvectors and Variance",
                description="How PCA eigenvectors relate to maximal variance directions.",
            )
            session.handle("/ask Why does an HTTP ETag help with cache validation?")
            insight_query = next(
                kwargs["query_texts"]
                for _, kwargs in session.vector_db.queries
                if kwargs["collection_name"] == "insights"
            )
            assert insight_query == ["Why does an HTTP ETag help with cache validation?"]
            assert session.agent.question_topic_packets
            assert session.agent.topic_connection_packets
            assert session.sql_db.topic_exists("http_cache_validation")
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_previous_asks_are_deduped_and_exclude_current_question():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.vector_db.find_asks = lambda query, user_id=None: [
                query,
                "Why does a confidence interval not mean 95% probability for this parameter?",
                "Why does a confidence interval not mean 95% probability for this parameter?",
                "How does repeated sampling enter the interpretation?",
            ]
            previous = session._query_previous_asks("What does a confidence interval mean?")
            assert "What does a confidence interval mean?" not in previous
            assert previous.count("confidence interval") == 1
            assert "repeated sampling" in previous
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_question_followups_share_open_session():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle("/ask what is covariance?")
            first_session_id = session.active_session_id
            session.handle("Can you give me a geometric example?")
            assert session.active_session_id == first_session_id
            assert [ask[0] for ask in session.vector_db.asks] == [
                "what is covariance?",
                "Can you give me a geometric example?",
            ]
            assert session.vector_db.asks[0][1] == session.vector_db.asks[1][1]
            session.sql_db.cursor.execute(
                "SELECT status, conversation_path FROM learning_sessions WHERE id = ?",
                (first_session_id,),
            )
            row = session.sql_db.cursor.fetchone()
            assert row["status"] == "active"
            assert row["conversation_path"]
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_ask_finalizes_active_question_before_starting_new_question():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle("/ask what is covariance?")
            first_session_id = session.active_session_id

            result = session.handle("/ask why does an HTTP ETag help with cache validation?").text

            assert "Done. I saved this learning session." in result
            assert "New question:" in result
            assert "prediction and correction" in result.lower()
            assert "kalman_filter" in session.profile.topics
            assert session.mode == "question"
            assert session.active_session_id != first_session_id
            session.sql_db.cursor.execute(
                "SELECT status, summary FROM learning_sessions WHERE id = ?",
                (first_session_id,),
            )
            first = session.sql_db.cursor.fetchone()
            assert first["status"] == "done"
            assert first["summary"] == "prediction/correction and uncertainty became clearer"
            session.sql_db.cursor.execute(
                "SELECT status, metadata_json FROM learning_sessions WHERE id = ?",
                (session.active_session_id,),
            )
            current = session.sql_db.cursor.fetchone()
            assert current["status"] == "active"
            assert "HTTP ETag" in current["metadata_json"]
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_profile_update_gate_uses_model_evaluation_not_evidence_phrase_matching():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.conversation.append_user("Prediction then correction is the basic loop.")
            updated, notes = session._apply_topic_updates(
                [
                    TopicUpdateResponse(
                        topic_id="kalman_filter",
                        intuition=0.4,
                        details=0.1,
                        confidence=0.5,
                        evidence="User understands the basic loop.",
                    )
                ]
            )
            assert updated == ["kalman_filter"]
            assert "kalman_filter" in session.profile.topics
            assert session.agent.profile_gate_packets
            assert "User understands the basic loop." in session.agent.profile_gate_packets[-1]
            assert "The learner paraphrased prediction and correction." in notes[0]

            session.agent.profile_gate_accept = False
            updated, notes = session._apply_topic_updates(
                [
                    TopicUpdateResponse(
                        topic_id="unsupported_topic",
                        intuition=0.4,
                        details=0.1,
                        confidence=0.5,
                        evidence="User understood unsupported topic.",
                    )
                ]
            )
            assert updated == []
            assert notes == []
            assert "unsupported_topic" not in session.profile.topics
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_profile_topic_updates_use_canonical_graph_topic_ids():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.sql_db.upsert_topic("confidence_interval", name="Confidence Interval")

            updated, notes = session._apply_topic_updates(
                [
                    TopicUpdateResponse(
                        topic_id="confidence_intervals",
                        intuition=0.4,
                        details=0.1,
                        confidence=0.5,
                        evidence="The learner explained confidence interval interpretation.",
                    )
                ]
            )

            assert updated == ["confidence_interval"]
            assert "confidence_interval" in session.profile.topics
            assert "confidence_intervals" not in session.profile.topics
            session.sql_db.cursor.execute("SELECT COUNT(*) AS count FROM topics WHERE id LIKE 'confidence_interval%'")
            assert session.sql_db.cursor.fetchone()["count"] == 1
            assert notes
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_profile_finalizer_gets_existing_topic_candidates():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.sql_db.upsert_topic("confidence_interval", name="Confidence Interval")
            session.handle("/ask what is a confidence interval?")
            session.handle("/done")
            assert session.agent.topic_update_packets
            assert "confidence_interval" in session.agent.topic_update_packets[-1]
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_stale_question_sessions_are_abandoned_on_startup():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle("/ask what is covariance?")
            session.sql_db.cursor.execute(
                "UPDATE learning_sessions SET status = 'active' WHERE id = ?",
                (session.active_session_id,),
            )
            session.sql_db.conn.commit()
            LearningSession(
                user_id="tester",
                sql_db=session.sql_db,
                vector_db=FakeVectorDB(),
                profile=session.profile,
                agent=FakeAgent(),
            )
            session.sql_db.cursor.execute(
                "SELECT status FROM learning_sessions WHERE id = ?",
                (session.active_session_id,),
            )
            assert session.sql_db.cursor.fetchone()["status"] == "abandoned"
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_topic_session_links_do_not_create_self_edges():
    with TemporaryDirectory() as dirname:
        db = SQLDatabase(Path(dirname) / "data" / "test.db")
        db.connect_topic_to_session("session_1", ["Kalman filter"])
        db.cursor.execute("SELECT * FROM topic_edges WHERE topic1 = topic2")
        assert db.cursor.fetchall() == []
        assert db.upsert_topic_edge("kalman_filter", "Kalman Filter", "related") is False
        db.close()


def test_topic_aliases_merge_and_resolve():
    with TemporaryDirectory() as dirname:
        db = SQLDatabase(Path(dirname) / "data" / "test.db")
        db.upsert_topic("attention_mechanism", name="Attention Mechanism", aliases=["attention mechanisms"])
        assert db.resolve_topic_id("Attention Mechanisms") == "attention_mechanism"
        db.upsert_topic("attention mechanisms", name="Attention Mechanisms", aliases=["self attention"])
        assert db.resolve_topic_id("self attention") == "attention_mechanism"
        db.cursor.execute("SELECT COUNT(*) AS count FROM topics WHERE id LIKE 'attention%'")
        assert db.cursor.fetchone()["count"] == 1
        db.close()


def test_plural_topic_id_resolves_to_existing_singular_topic():
    with TemporaryDirectory() as dirname:
        db = SQLDatabase(Path(dirname) / "data" / "test.db")
        db.upsert_topic("confidence_interval", name="Confidence Interval")
        assert db.resolve_topic_id("confidence_intervals") == "confidence_interval"
        db.upsert_topic("confidence intervals", name="Confidence Intervals")
        db.cursor.execute("SELECT COUNT(*) AS count FROM topics WHERE id LIKE 'confidence_interval%'")
        assert db.cursor.fetchone()["count"] == 1
        db.close()


def test_topic_summaries_do_not_emit_null_descriptions():
    with TemporaryDirectory() as dirname:
        db = SQLDatabase(Path(dirname) / "data" / "test.db")
        db.upsert_topic("embeddings", name="Embeddings")
        summaries = db.get_topic_summaries()
        embeddings = next(item for item in summaries if item["topic_id"] == "embeddings")
        assert embeddings["description"] == ""
        db.close()


def test_graph_finalizer_gets_existing_topic_candidates():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.sql_db.upsert_topic("confidence_interval", name="Confidence Interval")
            session.handle("/ask what is a confidence interval?")
            session.handle("/done")
            assert session.agent.graph_update_packets
            assert "confidence_interval" in session.agent.graph_update_packets[-1]
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_graph_updates_skip_weak_invalid_and_self_edges():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            changed = session._apply_graph_updates(
                GraphUpdatesResponse(
                    topics=[
                        GraphTopicResponse(
                            topic_id="kalman_filter",
                            name="Kalman Filter",
                            description="Recursive estimator.",
                            confidence=0.8,
                            evidence="Session target.",
                        ),
                        GraphTopicResponse(
                            topic_id="maybe_topic",
                            name="Maybe Topic",
                            confidence=0.2,
                            evidence="Weak guess.",
                        ),
                    ],
                    edges=[
                        GraphEdgeResponse(
                            topic1="kalman_filter",
                            topic2="Kalman Filter",
                            relation_type="related",
                            confidence=0.9,
                            evidence="Duplicate alias.",
                        ),
                        GraphEdgeResponse(
                            topic1="covariance",
                            topic2="kalman_filter",
                            relation_type="prerequisite",
                            confidence=0.7,
                            evidence="Covariance supports uncertainty tracking.",
                        ),
                        GraphEdgeResponse(
                            topic1="noise",
                            topic2="kalman_filter",
                            relation_type="made_up_relation",
                            confidence=0.9,
                            evidence="Invalid relation.",
                        ),
                    ],
                )
            )
            assert changed == 2
            session.sql_db.cursor.execute("SELECT * FROM topic_edges")
            rows = session.sql_db.cursor.fetchall()
            assert len(rows) == 1
            assert rows[0]["topic1"] == "covariance"
            assert rows[0]["topic2"] == "kalman_filter"
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_graph_updates_are_limited_before_persistence():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            limited = session._limit_graph_updates(
                GraphUpdatesResponse(
                    topics=[
                        GraphTopicResponse(topic_id="topic_1", confidence=0.1),
                        GraphTopicResponse(topic_id="topic_2", confidence=0.9),
                        GraphTopicResponse(topic_id="topic_3", confidence=0.7),
                        GraphTopicResponse(topic_id="topic_4", confidence=0.8),
                    ],
                    edges=[
                        GraphEdgeResponse(topic1="topic_1", topic2="topic_2", confidence=0.1),
                        GraphEdgeResponse(topic1="topic_2", topic2="topic_3", confidence=0.9),
                        GraphEdgeResponse(topic1="topic_3", topic2="topic_4", confidence=0.7),
                        GraphEdgeResponse(topic1="topic_4", topic2="topic_5", confidence=0.8),
                    ],
                )
            )
            assert [topic.topic_id for topic in limited.topics] == ["topic_2", "topic_4", "topic_3"]
            assert len(limited.edges) == 3
            assert limited.edges[-1].topic1 == "topic_3"
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_memory_updates_are_deduped_before_persistence():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            limited = session._dedupe_memories(
                [
                    MemoryUpdateResponse(type="insight", topic_id="topic_1", confidence=0.1, text="Weak."),
                    MemoryUpdateResponse(type="insight", topic_id="topic_2", confidence=0.9, text="Strong."),
                    MemoryUpdateResponse(type="confusion", topic_id="topic_3", confidence=0.7, text="Open."),
                    MemoryUpdateResponse(type="learning_preference", topic_id="topic_4", confidence=0.8, text="Style."),
                    MemoryUpdateResponse(type="successful_explanation", topic_id="topic_5", confidence=0.6, text="Move."),
                    MemoryUpdateResponse(type="insight", topic_id="topic_2", confidence=1.0, text="Duplicate."),
                ]
            )
            assert [(memory.kind.memory_type, memory.topic_id) for memory in limited] == [
                ("insight", "topic_1"),
                ("insight", "topic_2"),
                ("confusion", "topic_3"),
                ("learning_preference", "topic_4"),
                ("successful_explanation", "topic_5"),
            ]
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_memory_buckets_convert_to_extracted_memories():
    memories = SessionMemoryExtractionResponse.model_validate(
        {
            "confusions": [
                {"topic_id": "confidence_interval", "text": "Still confuses coverage with posterior probability.", "confidence": 0.8}
            ],
            "partial_understandings": [
                {"topic_id": "confidence_interval", "text": "Partly understands procedure-level coverage but not single intervals.", "confidence": 0.75}
            ],
            "successful_explanations": [
                {"topic_id": "confidence_interval", "text": "Repeated-sampling contrast helped.", "confidence": 0.7}
            ],
            "learning_preferences": [
                {"topic_id": "confidence_interval", "text": "Prefers boundary cases.", "confidence": 0.6}
            ],
            "insights": [
                {"topic_id": "confidence_interval", "text": "Understands coverage as procedure-level.", "confidence": 0.9}
            ],
        }
    ).extracted_memories()
    assert [memory.kind.memory_type for memory in memories] == [
        "confusion",
        "partial_understanding",
        "successful_explanation",
        "learning_preference",
        "insight",
    ]


def test_graph_response_normalizes_null_text_before_limiting():
    result = GraphUpdatesResponse.model_validate(
        {
            "topics": [
                {
                    "topic_id": "empirical_risk_minimization",
                    "name": "Empirical Risk Minimization",
                    "description": "Risk minimization over training data.",
                    "confidence": 0.95,
                    "evidence": "Strong evidence.",
                },
                {
                    "topic_id": "embeddings",
                    "name": "Embeddings",
                    "description": None,
                    "confidence": 0.25,
                    "evidence": "Weak evidence.",
                },
            ],
            "edges": [
                {
                    "topic1": "embeddings",
                    "topic2": "representation_learning",
                    "relation_type": "application_of",
                    "confidence": 0.25,
                    "evidence": None,
                }
            ],
        }
    )
    assert result.topics[1].description == ""
    assert result.edges[0].evidence == ""


def test_topic_prompts_reject_cross_domain_word_overlap():
    prompts = [
        SESSION_TOPIC_UPDATES_PROMPT,
        PROFILE_UPDATE_GATE_PROMPT,
        QUESTION_TOPIC_RESOLUTION_PROMPT,
        TOPIC_GRAPH_CONNECTION_PROMPT,
    ]
    for prompt in prompts:
        assert "same domain" in prompt or "different domain" in prompt
        assert "state capacity" in prompt
        assert "React state" in prompt


def test_memory_extraction_prompt_has_hard_budget_and_failure_case():
    assert "Prefer fewer high-quality memories" in SESSION_MEMORY_EXTRACTION_PROMPT
    assert "confusions" in SESSION_MEMORY_EXTRACTION_PROMPT
    assert "partial_understandings" in SESSION_MEMORY_EXTRACTION_PROMPT
    assert "Fill \"insights\" last" in SESSION_MEMORY_EXTRACTION_PROMPT
    assert "Do not store generic domain facts" in SESSION_MEMORY_EXTRACTION_PROMPT
    assert "must name the reusable teaching move" in SESSION_MEMORY_EXTRACTION_PROMPT
    assert "grounded in learner evidence" in SESSION_MEMORY_EXTRACTION_PROMPT
    assert "return empty arrays" in SESSION_MEMORY_EXTRACTION_PROMPT.lower()


if __name__ == "__main__":
    test_schema_is_idempotent()
    test_find_learning_session_by_conversation_path()
    test_semantic_memories_can_be_marked_replaced()
    test_question_session_lifecycle_and_finalization()
    test_bare_message_starts_question_session()
    test_question_context_steers_away_from_generic_overview()
    test_question_memory_query_uses_graph_connected_profile_topics()
    test_unrelated_question_does_not_use_profile_topic_memory_hint()
    test_previous_asks_are_deduped_and_exclude_current_question()
    test_question_followups_share_open_session()
    test_ask_finalizes_active_question_before_starting_new_question()
    test_profile_update_gate_uses_model_evaluation_not_evidence_phrase_matching()
    test_profile_topic_updates_use_canonical_graph_topic_ids()
    test_profile_finalizer_gets_existing_topic_candidates()
    test_stale_question_sessions_are_abandoned_on_startup()
    test_topic_session_links_do_not_create_self_edges()
    test_topic_aliases_merge_and_resolve()
    test_plural_topic_id_resolves_to_existing_singular_topic()
    test_topic_summaries_do_not_emit_null_descriptions()
    test_graph_finalizer_gets_existing_topic_candidates()
    test_graph_updates_skip_weak_invalid_and_self_edges()
    test_memory_updates_are_deduped_before_persistence()
    test_memory_buckets_convert_to_extracted_memories()
    test_graph_updates_are_limited_before_persistence()
    test_graph_response_normalizes_null_text_before_limiting()
    test_topic_prompts_reject_cross_domain_word_overlap()
    test_memory_extraction_prompt_has_hard_budget_and_failure_case()
    print("learning session tests passed")
