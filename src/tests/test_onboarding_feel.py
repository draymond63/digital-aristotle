from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from brains.comms.onboarder import OnboardingBrain


CONVERSATION_NAME = "onboarding-feel-test"
PROFILE_NAME = "onboarding-feel-test"
SCRIPTED_ANSWERS = [
    "I keep wondering how people make tiny games and simulations, especially the parts where simple rules create surprising behavior.",
    "I studied some college math and I am comfortable with basic programming, especially a little Python.",
    "I have done a little Python, but I do not really know game loops or physics simulation yet.",
    "Examples and hands-on projects help most. I like visual explanations too.",
    "I want to walk away with a mental model and a tiny thing I made.",
    "Please avoid long lectures, jargon, and quiz vibes.",
]


def print_turn(role: str, content: str):
    print(f"\n{role.upper()}:")
    print(content)


def main():
    brain = OnboardingBrain(username=PROFILE_NAME)

    print_turn("assistant", "".join(brain.start()))
    for answer in SCRIPTED_ANSWERS:
        print_turn("user", answer)
        print_turn("assistant", "".join(brain.respond(answer)))

    brain.convo.save(CONVERSATION_NAME)
    print(f"\nSaved conversation to data/conversations/{CONVERSATION_NAME}.json")
    print(f"Saved profile to data/profiles/{PROFILE_NAME}.yaml")


if __name__ == "__main__":
    main()
