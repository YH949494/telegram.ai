import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from .classifier import classify
from .config import get_settings
from .db import log_message
from .responses import generate_reply, get_reaction

logger = logging.getLogger(__name__)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    settings = get_settings()
    text = message.text

    logger.info(
        "Received message chat_id=%s message_id=%s user_id=%s",
        message.chat_id,
        message.message_id,
        message.from_user.id if message.from_user else None,
    )

    if not settings.enable_tagging:
        logger.info("Tagging disabled; skipping classification")
        return

    category = classify(text)
    logger.info("Classified message_id=%s category=%s", message.message_id, category)

    log_message(category, update)

    if category in settings.auto_reply_categories and settings.enable_low_risk_auto_reply:
        reply_text = generate_reply(category, text)
        if reply_text:
            logger.info("Auto reply triggered for message_id=%s category=%s", message.message_id, category)
            kwargs = {}
            if settings.enable_threaded_replies:
                kwargs["reply_to_message_id"] = message.message_id
            await message.reply_text(reply_text, **kwargs)

        reaction = get_reaction(category)
        if reaction:
            kwargs = {}
            if settings.enable_threaded_replies:
                kwargs["reply_to_message_id"] = message.message_id
            await message.reply_text(reaction, **kwargs)

    if category in settings.suggestion_only_categories and settings.enable_suggestions:
        suggestion = generate_reply(category, text)
        if suggestion and settings.admin_chat_id:
            logger.info("Suggestion forwarded for message_id=%s category=%s", message.message_id, category)
            admin_text = (
                f"Suggestion for message {message.message_id} in chat {message.chat_id}:\n"
                f"User: {message.from_user.username or message.from_user.id if message.from_user else 'unknown'}\n"
                f"Category: {category}\n"
                f"Original: {text}\n"
                f"Suggested reply: {suggestion}"
            )
            await context.bot.send_message(chat_id=settings.admin_chat_id, text=admin_text)


def setup_application():
    settings = get_settings()
    application = ApplicationBuilder().token(settings.telegram_token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    return application


async def start_bot(application) -> None:
    await application.initialize()
    await application.start()
    await application.updater.start_polling()


async def stop_bot(application) -> None:
    try:
        if application.updater:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Telegram bot stopped")
    except Exception:
        logger.exception("Failed to stop Telegram bot cleanly")
