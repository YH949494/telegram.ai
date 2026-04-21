import logging
from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReactionTypeEmoji, Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

try:
    from .classifier import classify_message
except ImportError:
    from .classifier import classify

    def classify_message(text, settings):
        category = classify(text)
        if category in AUTO_REPLY_ALLOWED_CATEGORIES:
            action = "auto_reply"
            confidence = 0.8
        elif category in settings.suggestion_only_categories:
            action = "suggest_only"
            confidence = 0.7
        else:
            action = "ignore"
            confidence = 0.4
        return SimpleNamespace(
            category=category,
            action=action,
            confidence=confidence,
            suggested_reply="",
            reason="rule_fallback",
        )
from .config import get_settings
from .db import log_message
from .responses import generate_reply, get_reaction
from .throttle import auto_reply_throttle

logger = logging.getLogger(__name__)
AUTO_REPLY_ALLOWED_CATEGORIES = {"new_user", "win_share", "positive_signal"}


def _prepare_reply_payload(payload, allow_button: bool = False):
    if isinstance(payload, dict):
        reply_text = payload.get("text") or ""
        reply_markup = None
        if allow_button:
            button_text = payload.get("button_text")
            button_url = payload.get("button_url")
            if button_text and button_url:
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text=button_text, url=button_url)]]
                )
        return reply_text, reply_markup
    return payload or "", None


async def safe_add_reaction(
    *,
    bot,
    chat_id: int,
    message_id: int,
    emoji: str,
    flow: str,
) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        logger.warning(
            "Failed to add reaction chat_id=%s message_id=%s flow=%s emoji=%s",
            chat_id,
            message_id,
            flow,
            emoji,
            exc_info=True,
        )


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

    decision = classify_message(text, settings)
    category = getattr(decision, "category", "unknown")
    raw_action = getattr(decision, "action", "ignore")
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    suggested_reply = getattr(decision, "suggested_reply", "") or ""
    decision_reason = getattr(decision, "reason", "")

    if confidence < 0.5:
        action = "ignore"
    elif confidence < 0.75:
        action = "suggest_only"
    else:
        action = raw_action

    if action == "auto_reply" and category not in AUTO_REPLY_ALLOWED_CATEGORIES:
        action = "ignore"

    logger.info(
        "Classified message_id=%s category=%s action=%s confidence=%s",
        message.message_id,
        category,
        action,
        confidence,
    )

    throttle_blocked = False
    throttle_reason = "none"

    if action == "auto_reply" and settings.enable_low_risk_auto_reply:
        if category == "win_share":
            await safe_add_reaction(
                bot=context.bot,
                chat_id=message.chat_id,
                message_id=message.message_id,
                emoji="🔥",
                flow="win_share_intake",
            )

        user_id = message.from_user.id if message.from_user else 0
        try:
            throttle_decision = auto_reply_throttle.evaluate_auto_reply_throttle(
                chat_id=message.chat_id,
                user_id=user_id,
                category=category,
                text=text,
                settings=settings,
            )
        except Exception:
            logger.exception(
                "Auto-reply throttle evaluation failed; allowing reply message_id=%s category=%s",
                message.message_id,
                category,
            )
            throttle_decision = None

        if throttle_decision and not throttle_decision.allowed:
            throttle_blocked = True
            throttle_reason = throttle_decision.reason
            action = "ignore"
            logger.info(
                "Auto reply blocked message_id=%s chat_id=%s user_id=%s reason=%s normalized_hash=%s",
                message.message_id,
                message.chat_id,
                user_id,
                throttle_decision.reason,
                throttle_decision.normalized_text_hash,
            )
        else:
            if throttle_decision:
                logger.info(
                    "Auto reply allowed message_id=%s chat_id=%s user_id=%s category=%s normalized_hash=%s",
                    message.message_id,
                    message.chat_id,
                    user_id,
                    category,
                    throttle_decision.normalized_text_hash,
                )
            if suggested_reply:
                reply_payload = suggested_reply
                allow_button = False
            else:
                reply_payload = generate_reply(category, text)
                allow_button = True

            if category == "new_user":
                await safe_add_reaction(
                    bot=context.bot,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    emoji="🎉",
                    flow="new_user_onboarding",
                )

            reply_text, reply_markup = _prepare_reply_payload(
                reply_payload,
                allow_button=allow_button,
            )
            if reply_text:
                logger.info("Auto reply triggered for message_id=%s category=%s", message.message_id, category)
                kwargs = {}
                if settings.enable_threaded_replies:
                    kwargs["reply_to_message_id"] = message.message_id
                if reply_markup:
                    kwargs["reply_markup"] = reply_markup
                await message.reply_text(reply_text, **kwargs)

            reaction = get_reaction(category)
            if reaction:
                kwargs = {}
                if settings.enable_threaded_replies:
                    kwargs["reply_to_message_id"] = message.message_id
                await message.reply_text(reaction, **kwargs)

    log_message(
        category,
        update,
        decision={
            "category": category,
            "action": action,
            "confidence": confidence,
            "reason": decision_reason,
        },
        throttle_blocked=throttle_blocked,
        throttle_reason=throttle_reason,
    )

    if action == "suggest_only" and settings.enable_suggestions:
        suggestion_payload = suggested_reply or generate_reply(category, text)
        suggestion, _ = _prepare_reply_payload(suggestion_payload, allow_button=False)
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
