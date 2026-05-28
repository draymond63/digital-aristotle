from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import os

from brains.comms.agent_base import Conversation
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
        self.force_ready_on_first_goal_intake = False
        self.append_stray_both_to_goal = False
        self.never_ready_goal_intake = False
        self.fail_goal_intake = False
        self.goal_intake_packets = []

    def run_task_json(self, task, conversation, dynamic_prompts=None, packet=None):
        if task.name == "goal_intake":
            if self.fail_goal_intake:
                raise RuntimeError("model unavailable")
            self.goal_intake_packets.append(packet or "")
            user_turns = (packet or "").count("\nUser:")
            if self.force_ready_on_first_goal_intake and packet and user_turns == 1:
                return {
                    "status": "ready",
                    "question": "",
                    "resolved_goal": "statistical modelling and prediction Both",
                    "candidate_theme": "",
                    "adjacent_concepts": [],
                    "rationale": "Bad model response.",
                }
            if packet and "statistical modelling" in packet and user_turns == 1:
                return {
                    "status": "clarify",
                    "question": "",
                    "resolved_goal": "",
                    "candidate_theme": "probabilistic modelling for prediction under uncertainty",
                    "adjacent_concepts": [
                        "Bayesian inference",
                        "uncertainty calibration",
                        "model checking",
                        "decision-making under uncertainty",
                    ],
                    "rationale": "The user gave a cluster of examples around probabilistic modelling.",
                }
            if packet and "robotics better" in packet and user_turns == 1:
                return {
                    "status": "clarify",
                    "resolved_goal": "",
                    "question": "",
                    "candidate_theme": "autonomous robotics as perception-action loops",
                    "adjacent_concepts": [
                        "state estimation",
                        "world models",
                        "planning under uncertainty",
                        "feedback stability",
                    ],
                    "rationale": "The user gave a robotics topic cluster.",
                }
            if self.never_ready_goal_intake:
                return {
                    "status": "clarify",
                    "question": "Do you want theory, practical application, or both?",
                    "resolved_goal": "",
                    "candidate_theme": "",
                    "adjacent_concepts": [],
                    "rationale": "Keep clarifying.",
                }
            if packet and user_turns >= 2:
                if "statistical modelling" in packet:
                    return {
                        "status": "ready",
                        "question": "",
                        "resolved_goal": (
                            "build practical and theoretical skill in probabilistic modelling for prediction "
                            "and uncertainty"
                        ),
                        "candidate_theme": "",
                        "adjacent_concepts": [],
                        "rationale": "The learner accepted the central theme.",
                    }
                return {
                    "status": "ready",
                    "question": "",
                    "resolved_goal": (
                        "learn Kalman filters from a controls intuition perspective Both"
                        if self.append_stray_both_to_goal
                        else "learn Kalman filters from a controls intuition perspective"
                    ),
                    "candidate_theme": "",
                    "adjacent_concepts": [],
                    "rationale": "The learner clarified the angle.",
                }
            return {
                "status": "clarify",
                "question": "What angle should this goal take: intuition, math, or implementation?",
                "resolved_goal": "",
                "candidate_theme": "",
                "adjacent_concepts": [],
                "rationale": "The initial goal is broad.",
            }
        if task.name == "syllabus_planner":
            return {
                "title": "Kalman Filters",
                "target_topic": "kalman_filter",
                "milestones": [
                    {"title": "Prediction and correction", "objective": "Understand the filter loop."},
                    {"title": "Uncertainty", "objective": "Understand covariance and trust."},
                    {"title": "Worked example", "objective": "Track position and velocity."},
                ],
            }
        if task.name == "state_eval":
            return {
                "understanding": 0.2,
                "confidence": 0.9,
                "intent": "continue",
                "evidence": "test",
            }
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
                            "evidence": "Session target was Kalman filters.",
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
        if task.name == "question_goal_linker":
            return {"link": False, "goal_id": "", "confidence": 0.0, "evidence": "no"}
        raise AssertionError(f"Unexpected JSON task: {task.name}")

    def run_task(self, task, conversation, dynamic_prompts=None, packet=None):
        if task.name == "teacher":
            return "A Kalman filter alternates prediction and correction."
        if task.name == "understanding_check":
            return "If the measurement is noisy, should the estimate move more or less toward it?"
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


def create_kalman_goal(session: LearningSession):
    first = session.handle("/goal learn Kalman filters")
    assert "What angle" in first.text
    proposed = session.handle("controls intuition")
    assert "Reply yes to create it" in proposed.text
    return session.handle("yes")


def test_schema_is_idempotent():
    with TemporaryDirectory() as dirname:
        path = Path(dirname) / "data" / "test.db"
        SQLDatabase(path).close()
        SQLDatabase(path).close()
        db = SQLDatabase(path)
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_goals'")
        assert db.cursor.fetchone() is not None
        db.close()


def test_sql_database_can_be_used_from_worker_thread():
    with TemporaryDirectory() as dirname:
        db = SQLDatabase(Path(dirname) / "data" / "test.db")
        db.create_learning_goal("tester", "Kalman Filters", "learn Kalman filters", "kalman_filter")
        result = []

        def query_goal():
            result.append(db.get_recent_active_goal("tester")["title"])

        thread = threading.Thread(target=query_goal)
        thread.start()
        thread.join()
        assert result == ["Kalman Filters"]
        db.close()


def test_goal_lifecycle_and_finalization():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            created = create_kalman_goal(session)
            assert "Created learning goal: Kalman Filters" in created.text
            assert "Syllabus:" in created.text
            assert session.active_goal_id is not None

            goals = session.handle("/goals").text
            assert "Kalman Filters" in goals
            assert "Prediction and correction" in goals

            report = session.handle("/done").text
            assert "Today you clarified: prediction/correction and uncertainty became clearer" in report
            assert "Profile backup:" in report
            assert "Audit log:" in report
            assert "kalman_filter" in session.profile.topics
            assert session.vector_db.added
            assert session.vector_db.added[0][3][0]["user_id"] == "tester"
            assert session.vector_db.added[0][3][0]["topic_id"] == "kalman_filter"
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_goal_creation_clarifies_before_creating_syllabus():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            first = session.handle("/goal learn Kalman filters")
            assert "What angle" in first.text
            assert session.mode == "goal_intake"
            assert session.sql_db.get_active_goals("tester") == []

            proposed = session.handle("controls intuition")
            assert "Here is the goal I would create" in proposed.text
            assert session.mode == "goal_confirm"
            assert session.sql_db.get_active_goals("tester") == []

            created = session.handle("yes")
            assert "Created learning goal: Kalman Filters" in created.text
            assert session.mode == "goal"
            assert len(session.sql_db.get_active_goals("tester")) == 1
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_goal_intake_forces_first_turn_clarification_even_if_model_says_ready():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.agent.force_ready_on_first_goal_intake = True
            first = session.handle(
                "/goal I want to get better at statistical modelling and prediction. "
                "Things like gaussian processes, monte carlo simulations, feature weighting based on covariance, etc"
            )
            assert "Here is the goal I would create" not in first.text
            assert "cluster of examples" in first.text
            assert session.mode == "goal_intake"
            assert session.sql_db.get_active_goals("tester") == []
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_goal_intake_uses_general_topic_shaping_for_example_clusters():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            first = session.handle(
                "/goal I want to get better at statistical modelling and prediction. "
                "Things like gaussian processes, monte carlo simulations, feature weighting based on covariance, etc"
            )
            assert "probabilistic modelling for prediction under uncertainty" in first.text
            assert "decision-making under uncertainty" in first.text
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)

    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            robotics = make_session(Path(dirname))
            second = robotics.handle(
                "/goal I want to understand robotics better, like localization, path planning, "
                "sensor fusion, and control loops"
            )
            assert "autonomous robotics as perception-action loops" in second.text
            assert "world models" in second.text
            robotics.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_goal_intake_cleans_stray_option_suffix_from_resolved_goal():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.agent.append_stray_both_to_goal = True
            session.handle("/goal learn Kalman filters")
            proposal = session.handle("controls intuition")
            assert "Both" not in proposal.text
            assert session.pending_resolved_goal == "learn Kalman filters from a controls intuition perspective"
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_goal_intake_preserves_assistant_question_context_for_short_answers():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle(
                "/goal I want to get better at statistical modelling and prediction. "
                "Things like gaussian processes, monte carlo simulations, feature weighting based on covariance, etc"
            )
            session.handle("Both")
            packet = session.agent.goal_intake_packets[-1]
            session.sql_db.close()
            assert "Assistant:" in packet
            assert "probabilistic modelling for prediction under uncertainty" in packet
            assert "User: Both" in packet
        finally:
            os.chdir(old_cwd)


def test_goal_intake_generic_fallback_when_model_is_unavailable():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.agent.fail_goal_intake = True
            response = session.handle("/goal a fuzzy cluster of examples")
            assert "cluster of examples" in response.text
            assert "central theme" in response.text
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_goal_intake_carries_confirmed_adjacent_concepts_into_goal():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle(
                "/goal I want to get better at statistical modelling and prediction. "
                "Things like gaussian processes, monte carlo simulations, feature weighting based on covariance, etc"
            )
            proposal = session.handle("Yes, include adjacent ideas too")
            assert "decision-making under uncertainty" in proposal.text
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_goal_confirmation_can_be_revised_before_creation():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle("/goal learn Kalman filters")
            proposal = session.handle("controls intuition")
            assert "Reply yes" in proposal.text
            assert session.mode == "goal_confirm"

            revised = session.handle("make it implementation focused instead")
            assert "Here is the goal I would create" in revised.text
            assert session.mode == "goal_confirm"
            assert session.sql_db.get_active_goals("tester") == []

            created = session.handle("yes")
            assert "Created learning goal" in created.text
            assert len(session.sql_db.get_active_goals("tester")) == 1
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_one_off_question_does_not_create_goal():
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
            assert session.sql_db.get_active_goals("tester") == []
            assert session.mode == "question"
            session.sql_db.cursor.execute(
                "SELECT status, conversation_path FROM goal_sessions WHERE id = ?",
                (session.active_session_id,),
            )
            row = session.sql_db.cursor.fetchone()
            assert row["status"] == "active"
            assert row["conversation_path"]
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_one_off_question_followups_share_open_session_until_switch():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            session.handle("/ask what is covariance?")
            first_session_id = session.active_session_id
            session.handle("Can you give me a geometric example?")
            assert session.active_session_id == first_session_id
            session.sql_db.cursor.execute(
                "SELECT status, conversation_path FROM goal_sessions WHERE id = ?",
                (first_session_id,),
            )
            row = session.sql_db.cursor.fetchone()
            assert row["status"] == "active"
            assert row["conversation_path"]

            create_kalman_goal(session)
            session.sql_db.cursor.execute(
                "SELECT status FROM goal_sessions WHERE id = ?",
                (first_session_id,),
            )
            assert session.sql_db.cursor.fetchone()["status"] == "answered"
            assert session.mode == "goal"
            session.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_continue_resumes_recent_goal():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            create_kalman_goal(session)
            profile_text = session.handle("/profile").text
            assert "Profile for tester" in profile_text
            assert "Learning frontier" in profile_text
            resumed = LearningSession(
                user_id="tester",
                sql_db=session.sql_db,
                vector_db=FakeVectorDB(),
                profile=session.profile,
                agent=FakeAgent(),
            )
            result = resumed.handle("/continue").text
            assert "Picking up: Kalman Filters" in result
            assert "Prediction and correction" in result
            resumed.sql_db.close()
        finally:
            os.chdir(old_cwd)


def test_duplicate_goal_resumes_existing_goal():
    with TemporaryDirectory() as dirname:
        old_cwd = Path.cwd()
        try:
            session = make_session(Path(dirname))
            first = create_kalman_goal(session).text
            session.handle("/goal learn Kalman filters")
            session.handle("controls intuition")
            second = session.handle("yes").text
            assert "Created learning goal" in first
            assert "already have this active goal" in second
            assert len(session.sql_db.get_active_goals("tester")) == 1
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
                "UPDATE goal_sessions SET status = 'active' WHERE id = ?",
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
                "SELECT status FROM goal_sessions WHERE id = ?",
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
    test_sql_database_can_be_used_from_worker_thread()
    test_goal_lifecycle_and_finalization()
    test_goal_creation_clarifies_before_creating_syllabus()
    test_goal_intake_forces_first_turn_clarification_even_if_model_says_ready()
    test_goal_intake_uses_general_topic_shaping_for_example_clusters()
    test_goal_intake_cleans_stray_option_suffix_from_resolved_goal()
    test_goal_intake_preserves_assistant_question_context_for_short_answers()
    test_goal_intake_generic_fallback_when_model_is_unavailable()
    test_goal_intake_carries_confirmed_adjacent_concepts_into_goal()
    test_goal_confirmation_can_be_revised_before_creation()
    test_one_off_question_does_not_create_goal()
    test_one_off_question_followups_share_open_session_until_switch()
    test_continue_resumes_recent_goal()
    test_duplicate_goal_resumes_existing_goal()
    test_stale_question_sessions_are_abandoned_on_startup()
    test_topic_session_links_do_not_create_self_edges()
    test_topic_aliases_merge_and_resolve()
    test_graph_updates_skip_weak_invalid_and_self_edges()
    print("learning session tests passed")
