from dataclasses import dataclass
from enum import Enum
from typing import Optional

from agent import Agent
from db_sql import SQLDatabase
from db_vector import SemanticDatabase, Collection
from profile import Profile
from prompts import SYSTEM_PROMPT


# ============================================================
# ENUMS
# ============================================================



class Depth(str, Enum):
    INTUITION = "intuition"
    MATH = "math"
    IMPLEMENTATION = "implementation"


class EntryPoint(str, Enum):
    CONTINUE_LESSON = "continue_lesson"
    ASK_QUESTION = "ask_question"
    SUGGEST_TOPIC = "suggest_topic"
    GENERATE_LESSON_PLAN = "generate_lesson_plan"


# ============================================================
# REQUEST TYPES
# ============================================================


@dataclass
class LessonRequest:
    topic: Optional[str] = None


@dataclass
class LessonPlanRequest:
    topic: Optional[str] = None
    explicit_interest: Optional[str] = None


# ============================================================
# MAIN SYSTEM
# ============================================================

class Aristotle:

    def __init__(self, user="daniel"):
        self.llm = Agent()

        self.vector_db = SemanticDatabase()
        self.sql_db = SQLDatabase()
        self.profile = Profile.load_user(user)

        # self.curriculum_engine = curriculum_engine
        # self.memory_engine = (memory_engine)
        # self.topic_graph = topic_graph

    # ========================================================
    # ENTRY POINTS
    # ========================================================

    def continue_lesson(self, request: LessonRequest):
        ...

    def ask_question(self, question: str):
        """
        One-off question answering path.
        """
        topics = self.llm.identify_topics(question)

        prompt = self._build_question_prompt(
            question=question,
            topics=topics,
        )

        response = self.llm.generate(prompt)

        # self._post_interaction_update(
        #     user_input=question,
        #     response=response,
        #     topic=topics,
        # )

        return response

    def suggest_topic(self):
        ...

    def generate_lesson_plan(self, request: LessonPlanRequest):
        ...

    # ========================================================
    # LESSON LOOP
    # ========================================================

    def submit_lesson_response(self, topic: str, user_response: str):
        """
        Closed-loop tutoring update.
        """
        ...

    # ========================================================
    # INTERNALS
    # ========================================================


    def _build_question_prompt(self, question: str, topics: list) -> list[dict[str, str]]:
        """
        Build in order, to optimize KV cache
        [
            static_system,
            persistent_user_model,
            retrieved_memories,
            current_lesson_state,
            recent_conversation,
            current_user_message
        ]
        """
        insights = self.vector_db.query(
            collection_name=Collection.insight,
            query_texts=[question, f"topics: {topics}"],
            n_results=5,
        )
        related_topics = self.sql_db.get_related_topics(topics)

        prompt = SYSTEM_PROMPT + "\n\n"
        prompt += f"User profile:\n{self.profile}\n\n"
        prompt += f"Retrieved insights:\n{insights}\n\n"
        prompt += f"Related topics:\n{related_topics}\n\n"

        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ]

    def _evaluate_understanding(self, topic: str, response: str):
        prompt = {
            "task": "evaluate_understanding",
            "topic": topic,
            "response": response,
        }

        return self.llm.generate(prompt)

    def _update_mastery(self, topic: str, evaluation):
        self.profile.update_domain(
            topic,
            evaluation,
        )

        self.sql_db.log_mastery_event(
            topic,
            evaluation,
        )

    def _decide_next_teaching_action(self, evaluation):
        if evaluation["understanding"] < 0.4:
            return "clarify"

        if evaluation["understanding"] < 0.7:
            return "probe_deeper"

        return "advance"

    def _post_interaction_update(self, user_input: str, response: str, topic: str):

        memories = self.memory_engine.extract(
            user_input=user_input,
            response=response,
            topic=topic,
        )

        self.memory_engine.store(memories)

        self.sql_db.log_event(
            topic=topic,
            content=user_input,
        )




if __name__ == "__main__":
    Aristotle().ask_question("How is inductance derived from spin?")