from brains.comms.agent_base import Brain, TaskedAgent, EvalAgent
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
        self.tester = TaskedAgent("assistant", ONBOARDING_PROMPT)
        self.evaluator = TaskedAgent("evaluator", PROFILE_EXTRACTION_PROMPT, temperature=0.0)
        self.dimensions_to_cover = list(self.user_dimensions.items())
        self.curr_dim = -1
        self.question_num = 0

    @property
    def current_dimension(self):
        return self.dimensions_to_cover[self.curr_dim]

    def start(self):
        self.next_section()
        for message in self.tester.stream_response(self.convo):
            self.convo.append(message)
            yield message

    def respond(self, user_message: str):
        self.add_usr_msg(user_message)

        yield from self._get_response()

        self.question_num += 1
        if self.question_num == 3:
            self.eval_convo()
            self.next_section()
            yield from self._get_response()

    def _get_response(self):
        print("Responding...")
        for message in self.tester.stream_response(self.convo):
            self.convo.append(message)
            yield message

    def eval_convo(self):
        print(self.evaluator.get_json(self.convo))
        # TODO: Update state?

    def next_section(self):
        self.question_num = 0
        self.curr_dim += 1
        dimension, meaning = self.current_dimension
        self.wipe()
        self.convo.append(self.evaluator.wrap_msg(f"Understand user's {meaning}"))

    # TODO: Middle to evaluate end of conversation, or get the tester to emit hidden state at the bottom




if __name__ == "__main__":
    brain = OnboardingBrain()
    list(brain.start())
    while True:
        message = input("\nUser: ")
        if message == "":
            break
        list(brain.respond(message))
    brain.save()