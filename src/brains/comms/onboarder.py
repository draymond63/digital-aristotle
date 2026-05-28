from brains.comms.agent_base import Brain, Task, Conversation, get_control_model
from brains.comms.prompts_onboarder import *
from brains.data.profile import Profile
from brains.data.profile import normalize_identifier



class OnboardingBrain(Brain):
    user_dimensions = {
        "curiosity_anchor": (
            "what the learner wants to explore first, or whether they need help finding a starting point."
        ),
        "background": (
            "the learner's informal education level, fields, or prior experience that should guide teaching assumptions."
        ),
        "learning_texture": (
            "how the learner wants explanations to feel, what outcomes are useful, and what to avoid."
        ),
    }
    question_text = {
        "curiosity_anchor": (
            "What would you like to explore first? It can be a topic, a vague curiosity, "
            "or you can say you are not sure and I will help find a starting point."
        ),
        "background": (
            "What should I know about your background so I do not explain things at the wrong level?"
        ),
        "learning_texture": (
            "How should learning with me feel? For example: intuitive, hands-on, visual, rigorous, "
            "project-based, no jargon, no long lectures, or something else."
        ),
    }
    unsure_prompt = (
        "Totally fine. We can finish setup without picking a topic, and you can ask or start a goal later."
    )
    questions_per_dimension = 1

    def __init__(self, username: str = "daniel", messages=None):
        self.username = username
        self.profile_seed = None
        self.helped_find_curiosity = False
        self.curiosity_answer = None
        super().__init__(messages)

    def __post_init__(self):
        self.ask_task = Task(
            "onboarding_question",
            ONBOARDING_PROMPT,
            model=get_control_model(),
            visible_history=6,
            temperature=0.4,
            num_predict=90,
        )
        self.transition_task = Task(
            "onboarding_transition",
            ONBOARDING_TRANSITION_PROMPT,
            model=get_control_model(),
            context_format="packet",
            temperature=0.3,
            num_predict=90,
        )
        self.evaluation_task = Task(
            "onboarding_profile_extraction",
            PROFILE_EXTRACTION_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=8,
            output_format="json",
            temperature=0.0,
            num_predict=360,
        )
        self.complete_task = Task(
            "onboarding_complete",
            ONBOARDING_COMPLETE_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            temperature=0.4,
            num_predict=120,
        )
        self.profile_seed_task = Task(
            "onboarding_profile_seed",
            PROFILE_SEED_PROMPT,
            model=get_control_model(),
            context_format="transcript",
            visible_history=None,
            output_format="json",
            temperature=0.0,
            num_predict=700,
        )
        self.dimensions_to_cover = list(self.user_dimensions.items())
        self.field_index = 0
        self.turns_in_field = 0
        self.field_start_index = 0

    @property
    def current_dimension(self):
        return self.dimensions_to_cover[self.field_index]

    def start(self):
        self.field_index = 0
        self.turns_in_field = 0
        self.field_start_index = len(self.convo)
        yield from self.ask_current_question()

    def respond(self, user_message: str):
        if self.profile_seed is not None:
            yield "You are set up. Ask me anything, or turn something into a longer goal when it feels worth tracking."
            return

        self.add_usr_msg(user_message)

        if self.current_dimension[0] == "curiosity_anchor" and self._is_uncertain_curiosity(user_message):
            self.helped_find_curiosity = True
            self.curiosity_answer = None
            yield from self._emit_onboarding_message(self.unsure_prompt)
            yield from self.advance_field()
            return

        if (
            self.current_dimension[0] == "curiosity_anchor"
            and not self._is_uncertain_curiosity(user_message)
            and not self._looks_like_curiosity(user_message)
        ):
            yield from self.ask_current_question()
            return

        if self.current_dimension[0] == "curiosity_anchor" and self._looks_like_curiosity(user_message):
            self.curiosity_answer = user_message.strip()

        self.turns_in_field += 1
        if self.turns_in_field >= self.questions_per_dimension:
            self.evaluate_section()
            yield from self.advance_field()
            return

        yield from self.ask_current_question()

    def ask_current_question(self):
        dimension, _ = self.current_dimension
        yield from self._emit_onboarding_message(self.question_text[dimension])

    def evaluate_section(self):
        result = self.run_task_json(
            self.evaluation_task,
            self.current_section(),
            dynamic_prompts=[self.current_field_prompt()],
        )
        return result

    def advance_field(self):
        if self.field_index + 1 >= len(self.dimensions_to_cover):
            yield from self.complete_onboarding()
            return

        self.field_index += 1
        self.turns_in_field = 0
        self.field_start_index = len(self.convo)
        yield from self.ask_current_question()

    def transition_to_next_topic(self):
        yield from self.advance_field()

    def transition_to(self, topic: str, meaning: str):
        previous_section = self.current_section()
        self.turns_in_field = 0
        packet = self._transition_packet(previous_section, topic, meaning)
        self.field_start_index = len(self.convo)
        yield from self.stream_task(
            self.transition_task,
            Conversation(),
            dynamic_prompts=[ASSESSMENT_TRANSITION_PROMPT(topic, meaning)],
            packet=packet,
        )

    def complete_onboarding(self):
        self.prepopulate_profile()
        yield from self.stream_task(
            self.complete_task,
            self.convo.visible_messages(),
        )

    def current_section(self):
        return Conversation(list(self.convo)[self.field_start_index:]).visible_messages()

    def current_field_prompt(self):
        dimension, meaning = self.current_dimension
        return ASSESSMENT_TRANSITION_PROMPT(dimension, meaning)

    def first_curiosity_answer(self) -> str | None:
        return self.curiosity_answer

    def _emit_onboarding_message(self, text: str):
        self.convo.append_task_result(self.ask_task, text)
        yield text

    @staticmethod
    def _is_uncertain_curiosity(user_message: str) -> bool:
        normalized = normalize_identifier(user_message)
        uncertain_phrases = (
            "i_don_t_know",
            "dont_know",
            "not_sure",
            "no_idea",
            "unsure",
            "nothing_in_mind",
            "no_clue",
            "you_choose",
            "surprise_me",
        )
        return any(phrase in normalized for phrase in uncertain_phrases)

    @classmethod
    def _looks_like_curiosity(cls, user_message: str) -> bool:
        normalized = normalize_identifier(user_message)
        if not normalized or cls._is_uncertain_curiosity(user_message):
            return False
        non_curiosity_starts = {
            "hi",
            "hello",
            "hey",
            "yo",
            "sup",
            "start",
            "lets_start",
            "let_s_start",
            "ok",
            "okay",
            "sure",
            "yes",
            "yep",
        }
        if normalized in non_curiosity_starts:
            return False
        return len(normalized) >= 8

    def prepopulate_profile(self):
        seed = self.run_task_json(
            self.profile_seed_task,
            self.convo.visible_messages(),
        )
        self.profile_seed = seed
        self.apply_profile_seed(seed)

    def apply_profile_seed(self, seed: dict):
        profile = Profile.load_user(self.username)

        for category, value in seed.get("background", {}).items():
            profile.update_background(category, value)

        for topic_id, topic_state in seed.get("topics", {}).items():
            profile.update_topic(topic_id, **topic_state)

        for category, items in seed.get("preferences", {}).items():
            for item in items:
                profile.update_preferences(category, item)

        for interest in seed.get("interests", []):
            profile.update_interests(interest)

        for topic_id in seed.get("current_topics", []):
            profile.add_current_topic(topic_id)

    def _transition_packet(self, previous_section: Conversation, dimension: str, meaning: str):
        transcript = "\n".join(
            f"{message.role.upper()}: {message.content}"
            for message in previous_section
        )
        return SECTION_TRANSITION_PROMPT(dimension, meaning, transcript)

    # TODO: Middle to evaluate end of conversation, or get the tester to emit hidden state at the bottom




if __name__ == "__main__":
    from brains.comms.agent_base import Conversation
    brain = OnboardingBrain()
    # list(brain.start())
    convo = Conversation.load(r"data\conversations\onboarding-1.json")[:-2]
    brain.set_convo(convo)
    list(brain.transition_to_next_topic())
    brain.chat_local()
