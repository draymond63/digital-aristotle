from pathlib import Path
from tempfile import TemporaryDirectory
import os

from brains.data.db_sql import SQLDatabase
from brains.data.profile import Profile
from brains.session import LearningSession


class FakeVectorDB:
    def __init__(self):
        self.added = []
        self.asks = []
        self.queries = []

    def log_ask(self, msg, session_id, user_id=None):
        self.asks.append((msg, session_id, user_id))

    def query_pretty(self, *args, **kwargs):
        self.queries.append((args, kwargs))
        return ""

    def add(self, collection_name, ids, documents, metadatas=None):
        self.added.append((collection_name, ids, documents, metadatas))


class FakeAgent:
    def __init__(self):
        self.finalized = False
        self.profile_gate_accept = True
        self.profile_gate_packets = []
        self.question_topic_packets = []
        self.topic_connection_packets = []

    def run_task_json(self, task, conversation, dynamic_prompts=None, packet=None):
        if task.name == "session_finalizer":
            self.finalized = True
            return {
                "summary": "prediction/correction and uncertainty became clearer",
                "next_step": "connect covariance to position and velocity",
                "topic_updates": [
                    {
                        "topic_id": "kalman_filter",
                        "intuition": 0.4,
                        "details": 0.1,
                        "confidence": 0.5,
                        "evidence": "The learner paraphrased prediction and correction.",
                    }
                ],
                "memories": [
                    {
                        "type": "insight",
                        "topic_id": "kalman_filter",
                        "text": "Learner framed Kalman filtering as prediction then correction.",
                        "confidence": 0.8,
                    }
                ],
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
            }
        if task.name == "profile_update_gate":
            self.profile_gate_packets.append("\n".join(dynamic_prompts or []))
            return {
                "accept": self.profile_gate_accept,
                "reason": (
                    "The learner paraphrased prediction and correction."
                    if self.profile_gate_accept
                    else "The transcript does not support the proposed update."
                ),
            }
        if task.name == "question_topic_resolver":
            context = "\n".join(dynamic_prompts or [])
            user_text = "\n".join(message.content for message in conversation.visible_messages())
            self.question_topic_packets.append(f"{context}\n{user_text}")
            if "widest direction" in user_text.lower():
                return {
                    "topics": [
                        {
                            "topic_id": "pca_variance_maximization",
                            "name": "PCA Variance Maximization",
                            "description": "Why PCA preserves directions with the most variance.",
                            "confidence": 0.9,
                        }
                    ]
                }
            if "http etag" in user_text.lower():
                return {
                    "topics": [
                        {
                            "topic_id": "http_cache_validation",
                            "name": "HTTP Cache Validation",
                            "description": "How validators such as ETags avoid unnecessary transfer.",
                            "confidence": 0.9,
                        }
                    ]
                }
            return {"topics": [{"topic_id": "covariance", "name": "Covariance", "description": "", "confidence": 0.9}]}
        if task.name == "topic_graph_connection":
            context = "\n".join(dynamic_prompts or [])
            user_text = "\n".join(message.content for message in conversation.visible_messages())
            self.topic_connection_packets.append(f"{context}\n{user_text}")
            if "pca_variance_maximization" in user_text and "pca_eigenvectors_variance" in context:
                return {
                    "connections": [
                        {
                            "topic_id": "pca_eigenvectors_variance",
                            "relation_type": "related",
                            "confidence": 0.86,
                            "evidence": "Both topics concern PCA variance directions.",
                        }
                    ]
                }
            return {"connections": []}
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
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        removed_table = "learning_" + "go" + "als"
        assert removed_table not in {row["name"] for row in db.cursor.fetchall()}
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
                "successful_explanations",
                "learning_preferences",
            }
            assert all(kwargs["user_id"] == "tester" for _, kwargs in session.vector_db.queries)
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


def test_question_followups_share_open_session():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle("/ask what is covariance?")
            first_session_id = session.active_session_id
            session.handle("Can you give me a geometric example?")
            assert session.active_session_id == first_session_id
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


def test_profile_update_gate_uses_model_evaluation_not_evidence_phrase_matching():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.conversation.append_user("Prediction then correction is the basic loop.")
            updated, notes = session._apply_topic_updates(
                [
                    {
                        "topic_id": "kalman_filter",
                        "intuition": 0.4,
                        "details": 0.1,
                        "confidence": 0.5,
                        "evidence": "User understands the basic loop.",
                    }
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
                    {
                        "topic_id": "unsupported_topic",
                        "intuition": 0.4,
                        "details": 0.1,
                        "confidence": 0.5,
                        "evidence": "User understood unsupported topic.",
                    }
                ]
            )
            assert updated == []
            assert notes == []
            assert "unsupported_topic" not in session.profile.topics
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


def test_graph_updates_skip_weak_invalid_and_self_edges():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            changed = session._apply_graph_updates(
                {
                    "topics": [
                        {
                            "topic_id": "kalman_filter",
                            "name": "Kalman Filter",
                            "description": "Recursive estimator.",
                            "confidence": 0.8,
                            "evidence": "Session target.",
                        },
                        {
                            "topic_id": "maybe_topic",
                            "name": "Maybe Topic",
                            "confidence": 0.2,
                            "evidence": "Weak guess.",
                        },
                    ],
                    "edges": [
                        {
                            "topic1": "kalman_filter",
                            "topic2": "Kalman Filter",
                            "relation_type": "related",
                            "confidence": 0.9,
                            "evidence": "Duplicate alias.",
                        },
                        {
                            "topic1": "covariance",
                            "topic2": "kalman_filter",
                            "relation_type": "prerequisite",
                            "confidence": 0.7,
                            "evidence": "Covariance supports uncertainty tracking.",
                        },
                        {
                            "topic1": "noise",
                            "topic2": "kalman_filter",
                            "relation_type": "made_up_relation",
                            "confidence": 0.9,
                            "evidence": "Invalid relation.",
                        },
                    ],
                }
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


if __name__ == "__main__":
    test_schema_is_idempotent()
    test_question_session_lifecycle_and_finalization()
    test_bare_message_starts_question_session()
    test_question_context_steers_away_from_generic_overview()
    test_question_memory_query_uses_graph_connected_profile_topics()
    test_unrelated_question_does_not_use_profile_topic_memory_hint()
    test_question_followups_share_open_session()
    test_profile_update_gate_uses_model_evaluation_not_evidence_phrase_matching()
    test_stale_question_sessions_are_abandoned_on_startup()
    test_topic_session_links_do_not_create_self_edges()
    test_topic_aliases_merge_and_resolve()
    test_graph_updates_skip_weak_invalid_and_self_edges()
    print("learning session tests passed")
