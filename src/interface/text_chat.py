import os
import dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

from brains.main import Aristotle


class TextBot:
    def __init__(self, token: str):

        self.token = token
        self.agent = Aristotle()
        self.num_messages = 0
        self.messages = []

        self.app = ApplicationBuilder().token(self.token).build()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        # TODO: Add commands
        self.app.add_handler(CommandHandler("new", self.wipe_conversation))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Ready.")

    async def wipe_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.num_messages = 0
        self.messages = []
        await update.message.reply_text("Conversation history cleared.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"Received: {update}")

        user = update.message.chat.username
        user_id = update.message.chat.id
        user_text = update.message.text

        print(f"Received message from {user} ({user_id}): {user_text}")

        if self.num_messages == 0:
            prompt = self.agent.init_question(user_text)
            self.messages.append({"role": "system", "content": prompt})

        self.messages.append({"role": "user", "content": user_text})
        response = self.agent.llm.generate(self.messages)
        self.messages.append({"role": "assistant", "content": response.message.content})
        self.num_messages += 1

        await update.message.reply_text(response.message.content)

    def respond(self, text: str) -> str:
        print(f"Received user input: {text}")
        return f"You said: {text}"

    def run(self):
        self.app.run_polling()


if __name__ == "__main__":

    dotenv.load_dotenv()
    TOKEN = os.getenv("TELEGRAM_KEY")

    bot = TextBot(TOKEN)
    bot.run()