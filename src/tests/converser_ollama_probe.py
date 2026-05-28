from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from brains.comms.converser import ConversationBrain


SCRIPTED_MESSAGES = [
    "How does a Kalman filter work? Start with intuition, not equations.",
    "So it has a model prediction, then it corrects that prediction using the measurement?",
    "I am fuzzy on what the uncertainty part is doing.",
]


def print_turn(role: str, content: str):
    print(f"\n{role.upper()}:")
    print(content)


def last_state_eval(brain):
    for entry in reversed(list(brain.convo)):
        if entry.source == "state_eval":
            return entry.content
    return "{}"


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:3b-instruct-q4_K_M"
    brain = ConversationBrain()
    brain.agent.model = model
    brain.state_prompt = (
        "User profile: prefers geometric, systems-level intuition before formalism; "
        "dislikes excessive notation and repetitive basics."
    )

    print(f"Model: {model}")

    for message in SCRIPTED_MESSAGES:
        print_turn("user", message)
        response = "\n\n".join(brain.respond(message))
        print_turn("assistant", response)
        print(f"\n[state_eval: {last_state_eval(brain)}]")
        print(f"\n[mode: {brain.state.value}]")

    visible = brain.convo.visible_messages()
    print(f"\nVisible turns saved in memory: {len(visible)}")


if __name__ == "__main__":
    main()
