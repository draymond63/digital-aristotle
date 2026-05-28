from brains.comms.agent_base import Brain, Task, Conversation, get_control_model
from brains.comms.prompts_onboarder import *
from brains.data.profile import Profile



class OnboardingBrain(Brain):
    user_dimensions = {
        "curiosity_anchor": (
            "what the learner is curious about right now. "
            "Good question shape: What is something you have been curious about lately, even if it feels random, vague, or hard to explain?"
        ),
        "background": (
            "the learner's informal education level, fields, or prior experience that should guide teaching assumptions. "
            "Good question shape: What background should I know about you: school level, work experience, fields you know well, or things you are comfortable assuming?"
        ),
        "starting_point": (
            "what the learner already knows and where the exploration should begin. "
            "Good question shape: For that topic, should we start from brand new, the basics, something you have explored a bit, or somewhere deeper?"
        ),
        "learning_texture": (
            "what kinds of explanations or activities help things click. "
            "Good question shape: When learning something new, what usually helps it click: examples, stories, visuals, analogies, hands-on projects, big-picture maps, or discussion?"
        ),
        "desired_outcome": (
            "what would make the first session feel worthwhile. "
            "Good question shape: By the end of a good exploration, what would you like to walk away with: a clear explanation, a mental model, something made, next questions, a practical skill, or a surprising insight?"
        ),
        "avoid": (
            "what makes learning feel boring, frustrating, or too much like school. "
            "Good question shape: What should I avoid so this does not feel like school: jargon, long lectures, quizzes, homework, going too slowly, going too fast, too much theory, or too few examples?"
        ),
    }
    questions_per_dimension = 1

    def __init__(self, username: str = "daniel", messages=None):
        self.username = username
        self.profile_seed = None
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
            num_predict=180,
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
            num_predict=360,
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
        self.add_usr_msg(user_message)

        self.turns_in_field += 1
        if self.turns_in_field >= self.questions_per_dimension:
            self.evaluate_section()
            yield from self.advance_field()
            return

        yield from self.ask_current_question()

    def ask_current_question(self):
        print("Responding...")
        yield from self.stream_task(
            self.ask_task,
            self.current_section(),
            dynamic_prompts=[self.current_field_prompt()],
        )

    def evaluate_section(self):
        result = self.run_task_json(
            self.evaluation_task,
            self.current_section(),
            dynamic_prompts=[self.current_field_prompt()],
        )
        print(result)
        # TODO: Update state?

    def advance_field(self):
        if self.field_index + 1 >= len(self.dimensions_to_cover):
            yield from self.complete_onboarding()
            return

        previous_section = self.current_section()
        self.field_index += 1
        self.turns_in_field = 0
        dimension, meaning = self.current_dimension
        packet = self._transition_packet(previous_section, dimension, meaning)
        self.field_start_index = len(self.convo)
        yield from self.stream_task(
            self.transition_task,
            Conversation(),
            dynamic_prompts=[self.current_field_prompt()],
            packet=packet,
        )

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
