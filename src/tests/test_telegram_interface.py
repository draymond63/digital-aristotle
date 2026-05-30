from __future__ import annotations

import asyncio
import json
import os
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


from interface.text_chat import (
    BUTTON_ASK,
    BUTTON_DONE,
    BUTTON_HELP,
    BUTTON_PROFILE,
    TelegramConfig,
    TelegramTutorBot,
    load_config,
    split_telegram_text,
)


def is_keyboard_remove(markup):
    return markup is not None and markup.__class__.__name__ == "ReplyKeyboardRemove"


class FakeSession:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.calls = []
        self.mode = "idle"
        self.active_session_id = None

    def startup_message(self):
        return f"startup for {self.user_id}"

    def handle(self, text: str):
        self.calls.append(text)
        if text.startswith("/ask"):
            self.mode = "question"
            self.active_session_id = self.active_session_id or "question_session"
        elif not text.startswith("/"):
            self.mode = "question"
            self.active_session_id = self.active_session_id or "question_session"
        return SimpleNamespace(text=f"handled {text}", should_quit=False)


class FakeOnboarding:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.profile_seed = None
        self.started = False
        self.saved = False
        self.messages = []
        self.curiosity = "how tiny games work"

    def start(self):
        self.started = True
        yield f"onboarding start for {self.user_id}"

    def respond(self, text: str):
        self.messages.append(text)
        if text == "done onboarding":
            self.profile_seed = {"interests": ["math"]}
            yield "onboarding complete"
            return
        yield f"onboarding asked after {text}"

    def save(self):
        self.saved = True

    def first_curiosity_answer(self):
        return self.curiosity


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))


class FakeUpdate:
    def __init__(self, user_id=123, text="/start", username="tester", chat_id=None):
        self.effective_user = SimpleNamespace(
            id=user_id,
            username=username,
            first_name="Test",
            last_name="User",
        )
        self.effective_chat = SimpleNamespace(id=chat_id or user_id)
        self.message = FakeMessage(text)


def keyboard_text(markup):
    return tuple(tuple(button.text for button in row) for row in markup.keyboard)


def make_bot(tmpdir: Path, allowed_ids={123}, existing_profile=True):
    sessions = {}
    onboarders = {}

    def session_factory(user_id):
        session = FakeSession(user_id)
        sessions[user_id] = session
        return session

    def onboarding_factory(user_id):
        onboarding = FakeOnboarding(user_id)
        onboarders[user_id] = onboarding
        return onboarding

    bot = TelegramTutorBot(
        TelegramConfig(
            token="123:ABC",
            allowed_ids=set(allowed_ids),
            attempted_usage_path=tmpdir / "attempts.jsonl",
        ),
        session_factory=session_factory,
        onboarding_factory=onboarding_factory,
        profile_exists=lambda user_id: existing_profile,
        build_application=False,
    )
    return bot, sessions, onboarders


def test_start_initializes_user_session_and_keyboard():
    with TemporaryDirectory() as dirname:
        bot, sessions, _ = make_bot(Path(dirname))
        update = FakeUpdate(text="/start")
        asyncio.run(bot.start(update, SimpleNamespace()))
        assert "telegram_123" in sessions
        assert update.message.replies[0][0] == "startup for telegram_123"
        assert update.message.replies[0][1] is not None
        assert keyboard_text(update.message.replies[0][1]) == (
            ("Ask Question",),
            ("Profile", "Help"),
        )


def test_new_user_is_onboarded_before_options_or_session():
    with TemporaryDirectory() as dirname:
        bot, sessions, onboarders = make_bot(Path(dirname), existing_profile=False)
        update = FakeUpdate(text="/start")
        asyncio.run(bot.start(update, SimpleNamespace()))
        assert sessions == {}
        assert "telegram_123" in onboarders
        assert update.message.replies[0][0] == (
            "Before we begin, I am going to do a quick onboarding so I can tune the tutoring to you."
        )
        assert is_keyboard_remove(update.message.replies[0][1])
        assert update.message.replies[1][0] == "onboarding start for telegram_123"
        assert is_keyboard_remove(update.message.replies[1][1])


def test_new_user_messages_continue_onboarding_without_buttons():
    with TemporaryDirectory() as dirname:
        bot, sessions, onboarders = make_bot(Path(dirname), existing_profile=False)
        update = FakeUpdate(text="I like math")
        asyncio.run(bot.message(update, SimpleNamespace()))
        assert sessions == {}
        assert onboarders["telegram_123"].messages == ["I like math"]
        assert update.message.replies[0][0] == (
            "Before we begin, I am going to do a quick onboarding so I can tune the tutoring to you."
        )
        assert is_keyboard_remove(update.message.replies[0][1])
        assert update.message.replies[1][0] == "onboarding asked after I like math"
        assert is_keyboard_remove(update.message.replies[1][1])


def test_onboarding_intro_is_sent_only_once():
    with TemporaryDirectory() as dirname:
        bot, sessions, onboarders = make_bot(Path(dirname), existing_profile=False)
        first = FakeUpdate(text="I am not sure")
        asyncio.run(bot.message(first, SimpleNamespace()))
        second = FakeUpdate(text="maybe AI")
        asyncio.run(bot.message(second, SimpleNamespace()))
        assert first.message.replies[0][0].startswith("Before we begin")
        assert all(not reply[0].startswith("Before we begin") for reply in second.message.replies)
        assert sessions == {}
        assert "telegram_123" in onboarders


def test_onboarding_completion_creates_session_and_shows_options():
    with TemporaryDirectory() as dirname:
        bot, sessions, onboarders = make_bot(Path(dirname), existing_profile=False)
        update = FakeUpdate(text="done onboarding")
        asyncio.run(bot.message(update, SimpleNamespace()))
        assert onboarders["telegram_123"].saved is True
        assert "telegram_123" in sessions
        assert update.message.replies[0][0].startswith("Before we begin")
        assert is_keyboard_remove(update.message.replies[0][1])
        assert update.message.replies[1][0] == (
            "onboarding complete\n\n"
            "Let's start with that as a quick question.\n\n"
            "handled /ask how tiny games work"
        )
        assert update.message.replies[1][1] is not None
        assert keyboard_text(update.message.replies[1][1]) == (
            ("Ask Question",),
            ("Done", "Profile", "Help"),
        )
        assert bot._route_text(123, BUTTON_HELP) == "handled //help"
        assert sessions["telegram_123"].calls[0] == "/ask how tiny games work"


def test_onboarding_completion_without_topic_shows_exploratory_startup():
    with TemporaryDirectory() as dirname:
        bot, sessions, onboarders = make_bot(Path(dirname), existing_profile=False)
        bot._get_onboarding(123).curiosity = None
        update = FakeUpdate(text="done onboarding")
        asyncio.run(bot.message(update, SimpleNamespace()))
        assert onboarders["telegram_123"].saved is True
        assert "telegram_123" in sessions
        assert update.message.replies[0][0].startswith("Before we begin")
        assert "No topic picked" in update.message.replies[1][0]
        assert "Ask Question or /ask <question>" in update.message.replies[1][0]
        assert "startup for telegram_123" not in update.message.replies[1][0]
        assert sessions["telegram_123"].calls == []


def test_unauthorized_user_is_rejected_and_logged():
    with TemporaryDirectory() as dirname:
        tmpdir = Path(dirname)
        bot, sessions, _ = make_bot(tmpdir, allowed_ids={999})
        update = FakeUpdate(user_id=321, text="/start", username="outsider")
        asyncio.run(bot.start(update, SimpleNamespace()))
        assert sessions == {}
        assert update.message.replies[0][0] == "Sorry, this tutor is private right now."
        assert is_keyboard_remove(update.message.replies[0][1])
        records = (tmpdir / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(records) == 1
        record = json.loads(records[0])
        assert record["telegram_user_id"] == 321
        assert record["chat_id"] == 321
        assert record["username"] == "outsider"
        assert record["message_text"] == "/start"
        assert record["command"] == "start"


def test_ask_button_consumes_next_text_as_question_and_followups_continue():
    with TemporaryDirectory() as dirname:
        bot, sessions, _ = make_bot(Path(dirname))
        assert bot._route_text(123, BUTTON_ASK) == "What's your question?"
        assert bot._route_text(123, "what is covariance?") == "handled /ask what is covariance?"
        session = sessions["telegram_123"]
        first_session_id = session.active_session_id
        assert bot._route_text(123, "give me a geometric example") == "handled give me a geometric example"
        assert session.active_session_id == first_session_id
        assert session.calls == ["/ask what is covariance?", "give me a geometric example"]


def test_buttons_map_to_existing_commands():
    with TemporaryDirectory() as dirname:
        bot, sessions, _ = make_bot(Path(dirname))
        expected = {
            BUTTON_DONE: "/done",
            BUTTON_PROFILE: "//profile",
            BUTTON_HELP: "//help",
        }
        for button, command in expected.items():
            assert bot._route_text(123, button) == f"handled {command}"
        assert sessions["telegram_123"].calls == list(expected.values())


def test_keyboard_hides_done_without_active_session():
    with TemporaryDirectory() as dirname:
        bot, _, _ = make_bot(Path(dirname))
        bot._get_session(123)
        assert bot._button_rows(123) == [
            [BUTTON_ASK],
            [BUTTON_PROFILE, BUTTON_HELP],
        ]

        bot._route_text(123, "what is covariance?")
        assert bot._button_rows(123) == [
            [BUTTON_ASK],
            [BUTTON_DONE, BUTTON_PROFILE, BUTTON_HELP],
        ]


def test_slash_command_clears_pending_action():
    with TemporaryDirectory() as dirname:
        bot, sessions, _ = make_bot(Path(dirname))
        bot._route_text(123, BUTTON_ASK)
        assert bot._route_text(123, "//help") == "handled //help"
        assert bot._route_text(123, "plain followup") == "handled plain followup"
        assert sessions["telegram_123"].calls == ["//help", "plain followup"]


def test_long_responses_are_split_into_safe_chunks():
    text = "x" * 8001
    chunks = split_telegram_text(text)
    assert len(chunks) == 3
    assert all(len(chunk) <= 3900 for chunk in chunks)


def test_app_can_be_constructed_from_fake_env_without_network():
    with patch.dict(
        os.environ,
        {"TELEGRAM_KEY": "123:ABC", "TELEGRAM_ALLOWED_IDS": "123,456"},
        clear=True,
    ), patch("interface.text_chat.dotenv.load_dotenv"):
        config = load_config()
        assert config.allowed_ids == {123, 456}
        bot = TelegramTutorBot(config, build_application=True)
        assert bot.app is not None


if __name__ == "__main__":
    test_start_initializes_user_session_and_keyboard()
    test_new_user_is_onboarded_before_options_or_session()
    test_new_user_messages_continue_onboarding_without_buttons()
    test_onboarding_intro_is_sent_only_once()
    test_onboarding_completion_creates_session_and_shows_options()
    test_onboarding_completion_without_topic_shows_exploratory_startup()
    test_unauthorized_user_is_rejected_and_logged()
    test_ask_button_consumes_next_text_as_question_and_followups_continue()
    test_buttons_map_to_existing_commands()
    test_keyboard_hides_done_without_active_session()
    test_slash_command_clears_pending_action()
    test_long_responses_are_split_into_safe_chunks()
    test_app_can_be_constructed_from_fake_env_without_network()
    print("telegram interface tests passed")
