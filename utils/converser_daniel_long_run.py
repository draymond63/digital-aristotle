from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]

from brains.comms.converser import ConversationBrain
from brains.data.profile import Profile


SCRIPTED_MESSAGES = [
    "I want to understand Kalman filters intuitively. Start from the systems/control angle, not equations.",
    "So the filter is carrying a prediction forward, then blending in the sensor measurement when it arrives?",
    "What exactly is the uncertainty tracking? Is it just a confidence score?",
    "If the sensor gets noisier, I think the filter should trust the model more and move less toward the measurement.",
    "How does it know whether the model or measurement is more trustworthy at a given step?",
    "I am getting the trust-balancing idea, but I do not see why the covariance has to be a matrix.",
    "So the matrix is tracking not just uncertainty in each variable, but how errors in variables move together?",
    "Can you connect this to a real example, like estimating position and velocity from noisy position measurements?",
]


def print_turn(role: str, content: str):
    print(f"\n{role.upper()}:")
    print(content)


def last_state_eval(brain: ConversationBrain):
    for entry in reversed(list(brain.convo)):
        if entry.source == "state_eval":
            return entry.content
    return "{}"


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "daniel"
    profile = Profile.load_user(username)

    brain = ConversationBrain()
    brain.state_prompt = (
        f"User profile for {username}:\n{profile}\n"
        "Use this profile quietly to calibrate explanations. The user prefers "
        "intuition before formalism and does not want repetitive basics."
    )

    print("Models: configured per Task")
    print(f"Teacher task model: {brain.teacher_task.model}")
    print(f"Check task model: {brain.check_task.model}")
    print(f"State eval task model: {brain.state_eval_task.model}")
    print(f"Profile: {profile.filepath}")

    for message in SCRIPTED_MESSAGES:
        print_turn("user", message)
        response = "\n\n".join(brain.respond(message))
        print_turn("assistant", response)
        print(f"\n[state_eval: {last_state_eval(brain)}]")
        print(f"[mode: {brain.state.value}]")

    filename = f"{username}-converser-long-run-{datetime.now().isoformat(timespec='seconds').replace(':', '-')}"
    brain.convo.save(filename)
    filepath = ROOT / "data" / "conversations" / f"{filename}.json"

    print(f"\nSaved conversation to {filepath}")
    print(f"Visible turns saved in memory: {len(brain.convo.visible_messages())}")


if __name__ == "__main__":
    main()
