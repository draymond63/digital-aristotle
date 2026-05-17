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
        self.finished = True

    @property
    def current_dimension(self):
        return self.dimensions_to_cover[self.curr_dim]

    def start(self):
        yield from self.respond("")

    def respond(self, user_message: str):
        if user_message:
            self.add_usr_msg(user_message)

        self.evaluate_state()

        if self.finished:
            self.curr_dim += 1
            dimension, meaning = self.current_dimension
            self.wipe()
            # message = self.
            self.convo.append(self.evaluator.wrap_msg(f"Understand user's {meaning}"))


        for message in self.tester.stream_response(self.convo):
            self.convo.append(message)
            yield message


    def evaluate_state(self):
        self.evaluator.get_json(self.convo)
        # TODO: Update state?

    # TODO: Middle to evaluate end of conversation, or get the tester to emit hidden state at the bottom




if __name__ == "__main__":
    brain = OnboardingBrain()
    list(brain.start())
    message = "Start!"
    while message != "":
        message = input("\nUser: ")
        list(brain.respond(message))
    brain.save()