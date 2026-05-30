from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


from brains.comms.onboarder import OnboardingBrain
from brains.session import LearningSession


logger = logging.getLogger(__name__)


MAX_TELEGRAM_MESSAGE_CHARS = 3900
ATTEMPT_LOG_PATH = Path("data/telegram_attempted_usage.jsonl")

BUTTON_ASK = "Ask Question"
BUTTON_DONE = "Done"
BUTTON_PROFILE = "Profile"
BUTTON_HELP = "Help"

BUTTON_TO_COMMAND = {
    BUTTON_DONE: "/done",
    BUTTON_PROFILE: "//profile",
    BUTTON_HELP: "//help",
}

COMMANDS = (
    "ask",
    "done",
)


@dataclass
class TelegramConfig:
    token: str
    allowed_ids: set[int]
    attempted_usage_path: Path = ATTEMPT_LOG_PATH


@dataclass
class TelegramReply:
    text: str
    include_keyboard: bool = True
    button_rows: list[list[str]] | None = None


def parse_allowed_ids(value: str | None) -> set[int]:
    if not value:
        return set()
    return {int(part.strip()) for part in value.split(",") if part.strip()}


def load_config() -> TelegramConfig:
    dotenv.load_dotenv()
    token = os.getenv("TELEGRAM_KEY")
    allowed_ids = parse_allowed_ids(os.getenv("TELEGRAM_ALLOWED_IDS"))
    if not token:
        raise RuntimeError("Set TELEGRAM_KEY in .env before running the Telegram bot.")
    if not allowed_ids:
        raise RuntimeError("Set TELEGRAM_ALLOWED_IDS in .env to a comma-separated allowlist.")
    return TelegramConfig(token=token, allowed_ids=allowed_ids)


def telegram_user_id(user_id: int) -> str:
    return f"telegram_{user_id}"


def keyboard_markup(button_rows: list[list[str]] | None = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        button_rows or [[BUTTON_ASK], [BUTTON_PROFILE, BUTTON_HELP]],
        resize_keyboard=True,
        is_persistent=True,
    )


def split_telegram_text(text: str, limit: int = MAX_TELEGRAM_MESSAGE_CHARS) -> list[str]:
    if not text:
        return []
    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


class TelegramTutorBot:
    def __init__(
        self,
        config: TelegramConfig,
        session_factory: Callable[[str], LearningSession] | None = None,
        onboarding_factory: Callable[[str], OnboardingBrain] | None = None,
        profile_exists: Callable[[str], bool] | None = None,
        build_application: bool = True,
    ):
        self.config = config
        self.session_factory = session_factory or (lambda user_id: LearningSession(user_id=user_id))
        self.onboarding_factory = onboarding_factory or (lambda user_id: OnboardingBrain(username=user_id))
        self.profile_exists = profile_exists or self._profile_exists
        self.sessions: dict[int, LearningSession] = {}
        self.onboarding: dict[int, OnboardingBrain] = {}
        self.onboarded_users: set[int] = set()
        self.onboarding_intro_sent: set[int] = set()
        self.pending_actions: dict[int, str] = {}
        self.last_one_off_questions: dict[int, str] = {}
        self.locks: dict[int, asyncio.Lock] = {}
        self.app: Application | None = None
        if build_application:
            self.app = self._build_application()

    @classmethod
    def from_env(cls, build_application: bool = True) -> "TelegramTutorBot":
        return cls(load_config(), build_application=build_application)

    def _build_application(self) -> Application:
        app = ApplicationBuilder().token(self.config.token).build()
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler(COMMANDS, self.command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))
        return app

    def run(self):
        if not self.app:
            self.app = self._build_application()
        self.app.run_polling()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._guard_allowed(update):
            return
        user_id = self._telegram_id(update)
        if self._needs_onboarding(user_id):
            await self._send_onboarding_intro(update, user_id)
            reply = await asyncio.to_thread(self._start_onboarding, user_id)
            await self._reply(update, reply.text, include_keyboard=reply.include_keyboard)
            return
        session = self._get_session(user_id)
        button_rows = await asyncio.to_thread(self._button_rows, user_id)
        await self._reply(update, session.startup_message(), include_keyboard=True, button_rows=button_rows)

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._guard_allowed(update):
            return
        text = update.message.text if update.message else ""
        await self._handle_allowed_text(update, text)

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._guard_allowed(update):
            return
        text = update.message.text if update.message else ""
        await self._handle_allowed_text(update, text)

    async def _handle_allowed_text(self, update: Update, text: str):
        user_id = self._telegram_id(update)
        lock = self.locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            try:
                if self._needs_onboarding(user_id):
                    await self._send_onboarding_intro(update, user_id)
                    reply = await asyncio.to_thread(self._route_onboarding_text, user_id, text)
                else:
                    reply = await asyncio.to_thread(self._route_reply, user_id, text)
            except Exception:
                logger.exception(f"Unhandled Telegram routing error for user {user_id}")
                reply = TelegramReply(
                    "Something went wrong while I was thinking. I logged the error in the bot console."
                )
            await self._reply(
                update,
                reply.text,
                include_keyboard=reply.include_keyboard,
                button_rows=reply.button_rows,
            )

    def _start_onboarding(self, telegram_id: int) -> TelegramReply:
        if telegram_id in self.onboarding:
            return TelegramReply("Let's finish getting you set up first.", include_keyboard=False)
        brain = self._get_onboarding(telegram_id)
        response = "\n\n".join(brain.start())
        return TelegramReply(response, include_keyboard=False)

    async def _send_onboarding_intro(self, update: Update, telegram_id: int):
        if telegram_id in self.onboarding_intro_sent:
            return
        self.onboarding_intro_sent.add(telegram_id)
        await self._reply(
            update,
            "Before we begin, I am going to do a quick onboarding so I can tune the tutoring to you.",
            include_keyboard=False,
        )

    def _route_onboarding_text(self, telegram_id: int, text: str) -> TelegramReply:
        text = text.strip()
        if not text or text == "/start":
            return self._start_onboarding(telegram_id)
        brain = self._get_onboarding(telegram_id)
        response = "\n\n".join(brain.respond(text))
        if self._onboarding_complete(telegram_id, brain):
            first_question = brain.first_curiosity_answer()
            brain.save()
            self.onboarding.pop(telegram_id, None)
            self.onboarded_users.add(telegram_id)
            session = self._get_session(telegram_id)
            if first_question:
                self.last_one_off_questions[telegram_id] = first_question
                first_answer = session.handle(f"/ask {first_question}").text
                return TelegramReply(
                    f"{response}\n\nLet's start with that as a quick question.\n\n"
                    f"{first_answer}",
                    include_keyboard=True,
                    button_rows=self._button_rows(telegram_id),
                )
            return TelegramReply(
                f"{response}\n\n"
                "No topic picked, so I will not start a question yet.\n\n"
                "Next things you can do:\n"
                "- Ask Question or /ask <question> for a quick one-off.\n"
                "- Profile to see what I saved.\n"
                "- Help for the full command list.",
                include_keyboard=True,
                button_rows=self._button_rows(telegram_id),
            )
        return TelegramReply(response, include_keyboard=False)

    def _route_reply(self, telegram_id: int, text: str) -> TelegramReply:
        response = self._route_text(telegram_id, text)
        return TelegramReply(response, button_rows=self._button_rows(telegram_id))

    def _route_text(self, telegram_id: int, text: str) -> str:
        text = text.strip()
        session = self._get_session(telegram_id)
        if not text:
            return ""
        if text == BUTTON_ASK:
            self.pending_actions[telegram_id] = "ask"
            return "What's your question?"
        if text in BUTTON_TO_COMMAND:
            self.pending_actions.pop(telegram_id, None)
            return session.handle(BUTTON_TO_COMMAND[text]).text
        if text.startswith("/"):
            self.pending_actions.pop(telegram_id, None)
            self._remember_one_off_command(telegram_id, text)
            return session.handle(text).text

        pending = self.pending_actions.pop(telegram_id, None)
        if pending == "ask":
            self.last_one_off_questions[telegram_id] = text
            return session.handle(f"/ask {text}").text
        self.last_one_off_questions[telegram_id] = text
        return session.handle(text).text

    def _button_rows(self, telegram_id: int) -> list[list[str]]:
        rows = []
        rows.append([BUTTON_ASK])

        final_row = []
        if self._has_active_session(telegram_id):
            final_row.append(BUTTON_DONE)
        final_row.extend([BUTTON_PROFILE, BUTTON_HELP])
        rows.append(final_row)
        return rows

    def _has_active_session(self, telegram_id: int) -> bool:
        session = self.sessions.get(telegram_id)
        return bool(session and session.active_session_id)

    def _get_session(self, telegram_id: int) -> LearningSession:
        if telegram_id not in self.sessions:
            self.sessions[telegram_id] = self.session_factory(telegram_user_id(telegram_id))
        return self.sessions[telegram_id]

    def _remember_one_off_command(self, telegram_id: int, text: str):
        command, _, arg = text.partition(" ")
        if command.lower() == "/ask" and arg.strip():
            self.last_one_off_questions[telegram_id] = arg.strip()

    def _get_onboarding(self, telegram_id: int) -> OnboardingBrain:
        if telegram_id not in self.onboarding:
            self.onboarding[telegram_id] = self.onboarding_factory(telegram_user_id(telegram_id))
        return self.onboarding[telegram_id]

    def _needs_onboarding(self, telegram_id: int) -> bool:
        user_id = telegram_user_id(telegram_id)
        return (
            telegram_id in self.onboarding
            or (telegram_id not in self.onboarded_users and not self.profile_exists(user_id))
        )

    def _onboarding_complete(self, telegram_id: int, brain: OnboardingBrain) -> bool:
        return brain.profile_seed is not None or self.profile_exists(telegram_user_id(telegram_id))

    @staticmethod
    def _profile_exists(user_id: str) -> bool:
        return Path(f"data/profiles/{user_id}.yaml").exists()

    async def _guard_allowed(self, update: Update) -> bool:
        user_id = self._telegram_id(update)
        if user_id in self.config.allowed_ids:
            return True
        self._log_refused_attempt(update)
        await self._reply(update, "Sorry, this tutor is private right now.", include_keyboard=False)
        return False

    def _log_refused_attempt(self, update: Update):
        user = update.effective_user
        message = update.message
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "telegram_user_id": getattr(user, "id", None),
            "chat_id": getattr(update.effective_chat, "id", None),
            "username": getattr(user, "username", None),
            "first_name": getattr(user, "first_name", None),
            "last_name": getattr(user, "last_name", None),
            "message_text": getattr(message, "text", None),
            "command": self._command_name(getattr(message, "text", None)),
        }
        self.config.attempted_usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config.attempted_usage_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    @staticmethod
    def _command_name(text: str | None) -> str | None:
        if not text or not text.startswith("/"):
            return None
        return text.split(maxsplit=1)[0][1:].split("@", maxsplit=1)[0]

    @staticmethod
    def _telegram_id(update: Update) -> int:
        if not update.effective_user:
            raise RuntimeError("Telegram update has no effective user.")
        return int(update.effective_user.id)

    async def _reply(
        self,
        update: Update,
        text: str,
        include_keyboard: bool = True,
        button_rows: list[list[str]] | None = None,
    ):
        if not update.message:
            return
        chunks = split_telegram_text(text)
        if not chunks:
            return
        for index, chunk in enumerate(chunks):
            reply_markup = None
            if index == 0:
                reply_markup = keyboard_markup(button_rows) if include_keyboard else ReplyKeyboardRemove()
            await update.message.reply_text(
                chunk,
                reply_markup=reply_markup,
            )


if __name__ == "__main__":
    TelegramTutorBot.from_env().run()
