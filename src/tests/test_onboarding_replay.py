from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from brains.comms.agent_base import Conversation
from brains.comms.onboarder import OnboardingBrain


def load_until_state_change(filepath: Path) -> tuple[Conversation, str, str]:
    conversation = Conversation.load(filepath)

    evaluator_indices = [
        index for index, message in enumerate(conversation)
        if message.source == "evaluator"
    ]
    if len(evaluator_indices) < 2:
        raise RuntimeError("Expected at least two evaluator messages in replay file.")

    state_change_index = evaluator_indices[1]
    state_change = conversation[state_change_index]

    visible_messages = [
        message for message in conversation[:state_change_index]
        if message.source in ("user", "assistant")
    ]
    while visible_messages and visible_messages[-1].source != "user":
        visible_messages.pop()
    return Conversation(visible_messages), state_change.content, state_change.source


def main():
    filepath = ROOT / "data" / "conversations" / "onboarding-1.json"
    conversation, control_text, control_source = load_until_state_change(filepath)

    brain = OnboardingBrain()
    brain.set_convo(conversation)
    brain.field_index = 0

    print(f"Loaded {len(conversation)} visible messages.")
    print(f"Skipped persisted control message from {control_source!r}: {control_text!r}")
    print("Using transition agent for the next section.")
    print("\nMODEL RESPONSE:\n")

    for content in brain.transition_to_next_topic():
        print(content)


if __name__ == "__main__":
    main()
