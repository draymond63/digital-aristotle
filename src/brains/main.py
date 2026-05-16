from dataclasses import dataclass
from enum import Enum
from typing import Optional

from brains.brain_loops import ConversationBrain
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

        self.brain = ConversationBrain()
        self.vector_db = SemanticDatabase()
        self.sql_db = SQLDatabase()
        self.profile = Profile.load_user(user)

        # TODO: Improve message handling
        self.messages = []

        # self.curriculum_engine = curriculum_engine
        # self.memory_engine = (memory_engine)
        # self.topic_graph = topic_graph

    def save(self):
        import json
        from datetime import datetime
        filename = datetime.now().isoformat(timespec="seconds").replace(":", "-")
        with open(f"data/conversations/{filename}.json", "w+") as f:
            print(self.brain._messages)
            json.dump(self.brain._messages, f)

    # ========================================================
    # ENTRY POINTS
    # ========================================================        

    def continue_lesson(self, request: LessonRequest):
        ...

    def ask_question(self, question: str):
        """
        One-off question answering path.
        """
        prompt = self.build_relevant_user_info(question)
        self.brain.append_message("system", prompt)
        self.converse(question)

    def build_relevant_user_info(self, question: str) -> str:
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
        session_id = self.sql_db.log_session_start(user_id=self.user, message=question)
        self.vector_db.log_ask(question, session_id=session_id)
        topics = self.identify_topics(question)
        # Upload topics
        self.sql_db.connect_topic_to_session(session_id=session_id, topics=topics)

        insights = self.vector_db.query_pretty(
            collection_name=Collection.INSIGHTS,
            query_texts=[question, f"topics: {topics}"],
            n_results=5,
        )
        related_topics = self.sql_db.get_related_topics_pretty(topics)

        # TODO: Filter user profile to relevant domains
        prompt = f"User profile:\n{self.profile}\n\n"
        if len(insights):
            prompt += f"insights the user has had:\n{insights}\n\n"
        if len(related_topics):
            prompt += f"Related topics:\n{related_topics}\n\n"
        # print("Generated prompt for question:\n", prompt)
        return prompt

    def suggest_topic(self):
        ...

    def generate_lesson_plan(self, request: LessonPlanRequest):
        ...

    # ========================================================
    # LESSON LOOP
    # ========================================================

    def converse(self, message: str):
        """
        Open-ended conversation.
        """
        while message != "":
            self.brain.respond(message)
            message = input("\nUser: ")

    # ========================================================
    # INTERNALS
    # ========================================================

    def identify_topics(self, msg: str, threshold=0.5) -> list[str]:
        related_asks = self.vector_db.find_asks(query=msg)
        topics = self.sql_db.get_topics_from_related_asks(user_id=self.user, related_asks=related_asks)
        print("Retrieved topics from related asks:", topics)
        if not len(topics):
            topics = self.brain.llm.identify_topics(msg=msg, threshold=threshold)
            print("Identified topics from LLM:", topics)
        return topics



if __name__ == "__main__":
    ctrl = Aristotle()
    # ctrl.ask_question("why do some materials have higher permeability than others? What's happening at the atomic level?")
    ctrl.ask_question("How does a kalman filter work?")
    ctrl.save()
