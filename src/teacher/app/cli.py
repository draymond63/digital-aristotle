import argparse
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from teacher.session.controller import HELP_TEXT, LearningSession


PROMPT = "\nYou: "


def print_block(text: str):
    """Print a non-empty text block."""
    if text:
        print(text)


def run_cli(user_id: str):
    """Run the interactive terminal tutor."""
    session = LearningSession(user_id=user_id)
    print_block(session.startup_message())
    print("\nType //help for commands.")

    while True:
        try:
            message = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            result = session.handle("//quit")
            print_block(result.text)
            break

        if not message:
            continue

        result = session.handle(message)
        print_block(result.text)
        if result.should_quit:
            break


def main():
    """Parse CLI arguments and run the terminal app."""
    parser = argparse.ArgumentParser(description="AI Teacher CLI")
    parser.add_argument("--user", default="daniel", help="Profile/user id to use")
    parser.add_argument("--help-commands", action="store_true", help="Show in-chat commands and exit")
    args = parser.parse_args()

    if args.help_commands:
        print(HELP_TEXT)
        return

    run_cli(args.user)


if __name__ == "__main__":
    main()
