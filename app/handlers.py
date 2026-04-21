import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

from .classifier import classify
from .config import get_settings
from .db import log_message
from .responses import generate_reply, get_reaction

"""
Telegram message handlers and bot initialisation.

This module integrates the classifier and response logic into a Telegram bot using
python‑telegram‑bot v20.  Messages are processed asynchronously; depending on the
assigned category the bot either replies automatically or sends a suggestion to an
admin chat for human follow‑up.
"""


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main handler for incoming text messages.

    :param update: Telegram update containing the message.
    :param context: Telegram context.
    """
    message = update.message
    if not message or not message.text:
        return

    text = message.text
    category = classify(text)
    settings = get_settings()

    # Log the message to MongoDB (non‑blocking).
    try:
        log_message(category, update)
    except Exception:
        pass

    # Determine whether to auto reply or just suggest.
    if category in settings.auto_reply_categories:
        reply_text = generate_reply(category, text)
        if reply_text:
            # Reply under the original message to maintain thread context.
            await message.reply_text(
                reply_text,
                reply_to_message_id=message.message_id,
            )
        reaction = get_reaction(category)
        if reaction:
            # Send a reaction as a separate reply.  python‑telegram‑bot does not
            # yet support the built‑in reaction API, so we emulate a reaction by
            # sending the emoji as a quick acknowledgement.
            await message.reply_text(
                reaction,
                reply_to_message_id=message.message_id,
            )
    elif category in settings.suggestion_only_categories:
        # Generate a suggested reply and forward to admin chat.
        suggestion = generate_reply(category, text)
        if suggestion and settings.admin_chat_id:
            admin_text = (
                f"Suggestion for message {message.message_id} in chat {message.chat_id}:\n"
                f"User: {message.from_user.username or message.from_user.id}\n"
                f"Original: {text}\n"
                f"Suggested reply: {suggestion}"
            )
            await context.bot.send_message(chat_id=settings.admin_chat_id, text=admin_text)
    else:
        # Unknown or unhandled categories are ignored.
        return


def setup_application() -> "telegram.ext.Application":
    """
    Build and return a configured Application instance.

    The returned Application is ready to be started and will listen for text messages.
    """
    settings = get_settings()
    application = ApplicationBuilder().token(settings.telegram_token).build()
    # Add a single handler for all non‑command text messages.
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    return application


async def run_bot(application) -> None:
    """
    Initialise and start the bot.

    :param application: The Telegram Application instance.
    """
    await application.initialize()
    await application.start()
    # Keep the bot running.  Without idle(), the application would exit.
    await application.updater.start_polling()
