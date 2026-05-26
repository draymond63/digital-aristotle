from brains.comms.agent_base import Brain, Task, Conversation
from brains.comms.prompts_onboarder import *



class OnboardingBrain(Brain):
    user_dimensions = {
        "reasoning_quality": "quality of logical/mechanistic thinking",
        "abstraction_ability": "comfort moving between conceptual layers",
        "technical_depth": "sophistication in technical domains",
        "breadth": "diversity of demonstrated domains",
        "communication_clarity": "ability to express ideas precisely",
        "mathematical_maturity": "fluency with formal/quantitative reasoning",
    }

    def __post_init__(self):
        self.ask_task = Task("onboarding_question", ONBOARDING_PROMPT, visible_history=6, temperature=0.5)
        self.transition_task = Task(
            "onboarding_transition",
            ONBOARDING_TRANSITION_PROMPT,
            context_format="packet",
            temperature=0.3,
        )
        self.evaluation_task = Task(
            "onboarding_profile_extraction",
            PROFILE_EXTRACTION_PROMPT,
            context_format="transcript",
            visible_history=8,
            output_format="json",
            temperature=0.0,
        )
        self.dimensions_to_cover = list(self.user_dimensions.items())
        self.curr_dim = -1
        self.question_num = 0
        self.assessment_prompt = ""
        self.section_start_index = 0

    @property
    def current_dimension(self):
        return self.dimensions_to_cover[self.curr_dim]

    def start(self):
        self.set_next_topic()
        self.section_start_index = len(self.convo)
        yield from self.ask_current_question()

    def respond(self, user_message: str):
        self.add_usr_msg(user_message)

        self.question_num += 1
        if self.question_num == 3:
            self.evaluate_section()
            yield from self.transition_to_next_topic()
            return

        yield from self.ask_current_question()

    def ask_current_question(self):
        print("Responding...")
        yield from self.stream_task(
            self.ask_task,
            self.current_section(),
            dynamic_prompts=[self.assessment_prompt],
        )

    def evaluate_section(self):
        result = self.run_task_json(
            self.evaluation_task,
            self.current_section(),
            dynamic_prompts=[self.assessment_prompt],
        )
        print(result)
        # TODO: Update state?

    def transition_to_next_topic(self):
        dimension, meaning = self.set_next_topic()
        yield from self.transition_to(dimension, meaning)

    def transition_to(self, topic: str, meaning: str):
        previous_section = self.current_section()
        self.question_num = 0
        self.assessment_prompt = ASSESSMENT_TRANSITION_PROMPT(topic, meaning)

        packet = self._transition_packet(previous_section, topic, meaning)
        self.section_start_index = len(self.convo)
        yield from self.stream_task(
            self.transition_task,
            Conversation(),
            dynamic_prompts=[self.assessment_prompt],
            packet=packet,
        )

    def set_next_topic(self):
        self.question_num = 0
        self.curr_dim += 1
        dimension, meaning = self.current_dimension
        self.assessment_prompt = ASSESSMENT_TRANSITION_PROMPT(dimension, meaning)
        return dimension, meaning

    def current_section(self):
        return Conversation(list(self.convo)[self.section_start_index:]).visible_messages()

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
