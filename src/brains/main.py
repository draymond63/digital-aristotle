from dataclasses import dataclass
from enum import Enum
from typing import Optional

from brains.agent import Agent
from brains.db_sql import SQLDatabase
from brains.db_vector import SemanticDatabase, Collection
from brains.profile import Profile
from brains.prompts import *


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
        self.user = user

        self.llm = Agent()
        self.vector_db = SemanticDatabase()
        self.sql_db = SQLDatabase()
        self.profile = Profile.load_user(user)

        # TODO: Improve message handling
        self.messages = []

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
        prompt = self.init_question(question)


        # self._post_interaction_update(
        #     user_input=question,
        #     response=response,
        #     topic=topics,
        # )

        self.converse(prompt, question)

    def init_question(self, question: str) -> str:
        session_id = self.sql_db.log_session_start(user_id=self.user, message=question)
        self.vector_db.log_ask(question, session_id=session_id)
        topics = self.identify_topics(question)
        # Upload topics
        self.sql_db.connect_topic_to_session(session_id=session_id, topics=topics)

        prompt = self._build_question_prompt(
            question=question,
            topics=topics,
        )

        print("Generated prompt for question:\n", prompt)
        return prompt

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


    def converse(self, system: str, user: str):
        """
        Open-ended conversation.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        while user != "":
            response = self.llm.generate(messages)
            print(response.message.content)
            messages.append({"role": "assistant", "content": response.message.content})
            user = input("\nUser: ")
            print()
            messages.append({"role": "user", "content": user})
            # TODO: Add evaluation and feedback loop here

    # ========================================================
    # INTERNALS
    # ========================================================

    def identify_topics(self, msg: str, threshold=0.5) -> list[str]:
        related_asks = self.vector_db.find_asks(query=msg)
        topics = self.sql_db.get_topics_from_related_asks(user_id=self.user, related_asks=related_asks)
        print("Retrieved topics from related asks:", topics)
        if not len(topics):
            topics = self.llm.identify_topics(msg=msg, threshold=threshold)
            print("Identified topics from LLM:", topics)
        return topics

    def _build_question_prompt(self, question: str, topics: list) -> str:
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
            collection_name=Collection.INSIGHTS,
            query_texts=[question, f"topics: {topics}"],
            n_results=5,
        )
        related_topics = self.sql_db.get_related_topics_pretty(topics)

        prompt = TEACHER_PROMPT + "\n\n"
        # TODO: Filter user profile to relevant domains
        prompt += f"User profile:\n{self.profile}\n\n"
        if len(insights):
            prompt += f"insights the user has had:\n{self._pretty_vector_response(insights)}\n\n"
        if len(related_topics):
            prompt += f"Related topics:\n{related_topics}\n\n"

        return prompt
    
    def _pretty_vector_response(self, response):
        pretty = []
        for doc, dist in zip(response["documents"][0], response["distances"][0]):
            pretty.append(f"{doc} (dist: {dist:3f})")
        return "\n".join(pretty)

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
    response = Aristotle().ask_question("What at the atomic level causes inductance?")
    print(response)