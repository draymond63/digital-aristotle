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

        self.app = ApplicationBuilder().token(self.token).build()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        # TODO: Add commands
        self.app.add_handler(CommandHandler("new", self.wipe_conversation))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Ready.")

    async def wipe_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.agent.save()
        self.agent.brain.set_convo([])
        await update.message.reply_text("Conversation history cleared.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"Received: {update}")

        user = update.message.chat.username
        user_id = update.message.chat.id
        user_text = update.message.text

        print(f"Received message from {user} ({user_id}): {user_text}")

        if self.agent.brain.num_messages == 0:
            prompt = self.agent.build_relevant_user_info(user_text)
            self.agent.brain.append_message("system", prompt)

        responses = self.agent.brain.respond(user_text)
        for response in responses:
            print(response)
            await update.message.reply_text(response)

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