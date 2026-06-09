import logging
from pathlib import Path
import random
import re
from types import SimpleNamespace
from datetime import timedelta
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReactionTypeEmoji, Update
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

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

from .ai_decision import AIDecisionService
from .ai_budget import ai_budget_service
from .ai_reply import AIReplyService
from .config import get_settings
from .community_intelligence import classify_community_message
from .db import (
    log_message,
    log_suggestion,
    log_feedback,
    get_few_shot_examples,
    log_community_intelligence_event,
    aggregate_community_helper_events,
    log_community_helper_reply_event,
    count_recent_community_helper_replies,
)
from .engagement_posts import register_engagement_jobs, record_chat_activity
from .engagement_topics import register_engagement_topic_job
from .openai_client import OpenAIClient
from .reply_policy import ReplyPolicyService, SEED_REPLIES
from .responses import generate_reply, get_reaction, RESPONSES
from .seed_rotation import seed_rotation_service
from .throttle import auto_reply_throttle, reaction_cooldown
from .time_utils import normalize_utc_datetime, utc_now

logger = logging.getLogger(__name__)
AUTO_REPLY_ALLOWED_CATEGORIES = {"comeback_campaign", "new_user", "win_share", "positive_signal", "voucher_subscription"}
_ai_runtime = None
RECOMMENDATION_PATTERNS = [r"\brecommend(?:ed|ation)?\b", r"max\s*win", r"this\s+game\s+has", r"daily\s+recommendation", r"推荐", r"建议"]
RESULT_PATTERNS = [r"\bi\s+won\b", r"\bmy\s+win\b", r"\bcashed?\s*out\b", r"\bjackpot\b", r"\bwon\s+\d+(?:\.\d+)?x?\b", r"中奖", r"赢了"]
SUPPORT_PATTERNS = [r"\bvoucher\b", r"\bpromo\b", r"\bissue\b", r"\berror\b", r"\bcan't\b", r"无法", r"失败"]
NEW_USER_PATTERNS = [r"\bi'?m\s+new\b", r"\bi\s+am\s+new\b", r"\bjust\s+joined\b", r"\bnew\s+(?:here|member)\b", r"新人", r"新来的?", r"刚加入"]
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
ADMIN_MEMBER_STATUSES = {"administrator", "creator", "owner"}
GROUP_CHAT_TYPES = {"group", "supergroup"}


WELCOME_TEXT = (
    "Welcome to AdvantPlay!\n\n"
    "Play smarter. Earn rewards. Join the community.\n\n"
    "✅ Daily drops & events\n"
    "✅ Community rewards\n"
    "✅ Weekly leaderboard & XP\n"
    "✅ Exclusive member perks\n\n"
    "Start by claiming your first $1 welcome code 👇"
)
WELCOME_BUTTON_TEXT = "Claim Your $1"
WELCOME_BUTTON_URL = "https://t.me/APreferralV1_bot?start=start"
WELCOME_DELETE_DELAY_SECONDS = 180
OFFICIAL_CHANNEL_URLS = {"https://t.me/advantplayofficial", "http://t.me/advantplayofficial", "t.me/advantplayofficial"}




def _build_welcome_mentions(members, limit: int = 5) -> tuple[str, int]:
    mentions = []
    for member in members[:limit]:
        username = getattr(member, "username", None)
        if username:
            mentions.append(f"@{username}")
        else:
            mentions.append(member.mention_html())
    return " ".join(mentions), len(mentions)


def _is_welcome_chat_allowed(chat_id: int, target_chat_id) -> bool:
    if target_chat_id is None:
        return True
    return chat_id == target_chat_id


async def _send_welcome_message(message, welcome_text: str, keyboard, image_path: str):
    try:
        with Path(image_path).open("rb") as photo_file:
            return await message.reply_photo(
                photo=photo_file,
                caption=welcome_text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    except Exception:
        logger.warning(
            "welcome_image_send_failed chat_id=%s message_id=%s image_path=%s",
            message.chat_id,
            message.message_id,
            image_path,
            exc_info=True,
        )
        return await message.reply_text(welcome_text, reply_markup=keyboard, parse_mode="HTML")


async def delete_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data if context.job else {}
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if chat_id is None or message_id is None:
        logger.warning("welcome_delete_job_missing_payload")
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info("welcome_message_deleted chat_id=%s message_id=%s", chat_id, message_id)
    except Exception:
        # Fail-safe: ignore deletion failures (e.g., missing permission / message already deleted).
        logger.info("welcome_message_delete_skipped chat_id=%s message_id=%s", chat_id, message_id)


async def welcome_new_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or not message.new_chat_members:
        return

    settings = get_settings()
    if not _is_welcome_chat_allowed(message.chat_id, settings.welcome_target_chat_id):
        logger.info("welcome_skipped_chat_not_allowed chat_id=%s target_chat_id=%s", message.chat_id, settings.welcome_target_chat_id)
        return

    human_members = [member for member in message.new_chat_members if not member.is_bot]
    if not human_members:
        logger.info("welcome_skipped_no_human_members chat_id=%s message_id=%s", message.chat_id, message.message_id)
        return

    mentions_text, mentioned_count = _build_welcome_mentions(human_members, limit=5)
    logger.info(
        "welcome_members_grouped chat_id=%s join_message_id=%s human_count=%s mentioned_count=%s",
        message.chat_id,
        message.message_id,
        len(human_members),
        mentioned_count,
    )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text=WELCOME_BUTTON_TEXT, url=WELCOME_BUTTON_URL)]])
    welcome_text = f"🎉 Hello {mentions_text}\n\n{WELCOME_TEXT}"
    sent = await _send_welcome_message(message, welcome_text, keyboard, settings.welcome_image_path)
    logger.info("welcome_message_sent chat_id=%s message_id=%s human_count=%s", message.chat_id, sent.message_id, len(human_members))
    if context.job_queue:
        context.job_queue.run_once(
            delete_message_job,
            when=WELCOME_DELETE_DELAY_SECONDS,
            data={"chat_id": sent.chat_id, "message_id": sent.message_id},
            name=f"welcome_delete_{sent.chat_id}_{sent.message_id}",
        )
    else:
        logger.warning("welcome_delete_job_queue_unavailable chat_id=%s message_id=%s", sent.chat_id, sent.message_id)
_BLOCKED_LIVE_INTENT_PREFIXES = ("mywin_", "free_spin_")
_BLOCKED_LIVE_INTENTS = {"campaign_hashtag_signal", "new_user_start", "spam_or_abuse", "sensitive", "unknown"}


def _community_button_text_url(btn):
    text = None
    url = None
    if isinstance(btn, dict):
        text = btn.get("text")
        url = btn.get("url")
    else:
        text = getattr(btn, "text", None)
        url = getattr(btn, "url", None)
    text = text.strip() if isinstance(text, str) and text.strip() else None
    url = url.strip() if isinstance(url, str) and url.strip() else None
    return text, url


def _is_official_channel_button(text: str | None, url: str | None) -> bool:
    normalized_url = (url or "").strip().rstrip("/").lower()
    normalized_text = (text or "").strip().lower()
    return normalized_url in OFFICIAL_CHANNEL_URLS or (
        "official channel" in normalized_text and "advantplayofficial" in normalized_url
    )


def _prepare_reply_payload(payload, allow_button: bool = False, official_channel_cta_enabled: bool = False):
    if isinstance(payload, dict):
        reply_text = payload.get("text") or ""
        reply_markup = None
        if allow_button:
            button_text = payload.get("button_text")
            button_url = payload.get("button_url")
            if button_text and button_url and (
                official_channel_cta_enabled or not _is_official_channel_button(button_text, button_url)
            ):
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text=button_text, url=button_url)]]
                )
        return reply_text, reply_markup
    return payload or "", None


def _setting_number(settings, name: str, default, *, minimum=None, maximum=None):
    value = getattr(settings, name, default)
    try:
        value = type(default)(value)
    except (TypeError, ValueError):
        value = default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


async def safe_add_reaction(
    *,
    bot,
    chat_id: int,
    message_id: int,
    emoji: str,
    flow: str,
) -> bool:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
        return True
    except BadRequest as exc:
        if "Reaction_invalid" in str(exc):
            logger.info(
                "reaction_invalid_skipped chat_id=%s message_id=%s emoji=%s",
                chat_id,
                message_id,
                emoji,
            )
            return False
        logger.warning(
            "Failed to add reaction chat_id=%s message_id=%s flow=%s emoji=%s",
            chat_id,
            message_id,
            flow,
            emoji,
            exc_info=True,
        )
        return False
    except Exception:
        logger.warning(
            "Failed to add reaction chat_id=%s message_id=%s flow=%s emoji=%s",
            chat_id,
            message_id,
            flow,
            emoji,
            exc_info=True,
        )
        return False


def _build_ai_services(settings):
    client = OpenAIClient(api_key=settings.openai_api_key)
    return (
        client,
        AIDecisionService(client=client, model=settings.openai_decision_model),
        AIReplyService(client=client, model=settings.openai_generation_model),
        ReplyPolicyService(
            confidence_threshold=settings.ai_decision_confidence_threshold,
            generation_allowed_categories=settings.ai_generation_allowed_categories,
            seed_only_categories=settings.ai_seed_only_categories,
        ),
    )


def _get_ai_runtime(settings):
    global _ai_runtime
    if _ai_runtime is not None:
        return _ai_runtime
    if not settings.enable_ai_decision or not settings.openai_api_key:
        return None
    _ai_runtime = _build_ai_services(settings)
    return _ai_runtime


def _detect_text_features(text: str):
    lowered = (text or "").lower()
    has_recommendation = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in RECOMMENDATION_PATTERNS)
    has_result = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in RESULT_PATTERNS)
    has_support = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in SUPPORT_PATTERNS)
    has_new_user = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in NEW_USER_PATTERNS)
    return {
        "has_recommendation": has_recommendation,
        "has_result": has_result,
        "has_support": has_support,
        "has_new_user": has_new_user,
        "mixed_signal": has_recommendation and has_result,
    }


def has_mixed_intent(text: str) -> bool:
    return bool(_detect_text_features(text)["mixed_signal"])


def contains_cyrillic(text: str) -> bool:
    return bool(text and CYRILLIC_RE.search(text))


def _message_text_and_caption(message) -> str:
    parts = []
    for field in ("text", "caption"):
        value = getattr(message, field, None)
        if value:
            parts.append(str(value))
    return " ".join(parts)


def _is_group_or_supergroup_message(message) -> bool:
    chat = getattr(message, "chat", None)
    chat_type = getattr(chat, "type", None) or getattr(message, "chat_type", None)
    return chat_type in GROUP_CHAT_TYPES


async def _sender_is_admin_or_owner(message, context) -> bool:
    user = getattr(message, "from_user", None)
    bot = getattr(context, "bot", None)
    if not user or not bot or not hasattr(bot, "get_chat_member"):
        return False
    try:
        member = await bot.get_chat_member(chat_id=message.chat_id, user_id=user.id)
    except Exception:
        logger.warning(
            "[MODERATION_ADMIN_CHECK_FAILED] reason=cyrillic_language user_id=%s chat_id=%s message_id=%s",
            user.id,
            message.chat_id,
            message.message_id,
            exc_info=True,
        )
        return True
    return getattr(member, "status", None) in ADMIN_MEMBER_STATUSES


async def _delete_cyrillic_message_if_needed(message, context) -> bool:
    text = _message_text_and_caption(message)
    if not contains_cyrillic(text) or not _is_group_or_supergroup_message(message):
        return False

    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    if await _sender_is_admin_or_owner(message, context):
        logger.debug(
            "[MODERATION_SKIP] reason=cyrillic_language_admin user_id=%s chat_id=%s message_id=%s",
            user_id,
            message.chat_id,
            message.message_id,
        )
        return False

    try:
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
    except Exception as exc:
        logger.warning(
            "[MODERATION_DELETE_FAILED] reason=cyrillic_language error=%s user_id=%s chat_id=%s message_id=%s",
            exc,
            user_id,
            message.chat_id,
            message.message_id,
        )
        return True

    logger.info(
        "[MODERATION_DELETE] reason=cyrillic_language user_id=%s chat_id=%s message_id=%s",
        user_id,
        message.chat_id,
        message.message_id,
    )
    return True


async def cyrillic_caption_moderation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if context.bot and message.from_user and context.bot.id == message.from_user.id:
        return
    await _delete_cyrillic_message_if_needed(message, context)


def should_run_ai_decision(*, settings, text: str, rule_category: str, rule_confidence: float) -> bool:
    if not settings.enable_ai_decision or not settings.openai_api_key:
        return False
    if rule_category == "unknown":
        return True
    if rule_category in {"new_user", "voucher_question", "support_issue"} and rule_confidence >= 0.9:
        return False
    features = _detect_text_features(text)
    if rule_category == "win_share" and features["mixed_signal"]:
        return True
    if rule_confidence < settings.ai_rule_threshold:
        return True
    if rule_category in set(settings.ai_ambiguous_categories):
        return True
    return False


def _should_run_ai_decision(*, settings, category: str, confidence: float, text: str) -> bool:
    return should_run_ai_decision(
        settings=settings,
        text=text,
        rule_category=category,
        rule_confidence=confidence,
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    text = _message_text_and_caption(message)
    if not text:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if context.bot and message.from_user and context.bot.id == message.from_user.id:
        return
    if await _delete_cyrillic_message_if_needed(message, context):
        return

    settings = get_settings()
    if getattr(settings, "engagement_posts_enabled", False):
        try:
            record_chat_activity(chat_id=message.chat_id, message_at=normalize_utc_datetime(getattr(message, "date", None)) or utc_now())
        except Exception:
            logger.warning("chat_activity_record_failed chat_id=%s message_id=%s", message.chat_id, message.message_id, exc_info=True)

    has_photo = bool(getattr(message, "photo", None))
    has_video = bool(getattr(message, "video", None))

    logger.info(
        "Received message chat_id=%s message_id=%s user_id=%s snippet=%s",
        message.chat_id,
        message.message_id,
        message.from_user.id if message.from_user else None,
        text[:80],
    )

    if settings.community_helper_enabled:
        try:
            ci_decision = classify_community_message(
                text,
                has_photo=has_photo,
                has_video=has_video,
                user_id=message.from_user.id if message.from_user else None,
                username=message.from_user.username if message.from_user else None,
            )
            ci_doc = {
                "created_at": normalize_utc_datetime(getattr(message, "date", None)),
                "chat_id": message.chat_id,
                "message_id": message.message_id,
                "user_id": message.from_user.id if message.from_user else None,
                "username": message.from_user.username if message.from_user else None,
                "text_sample": text[:200],
                "fingerprint": ci_decision.fingerprint,
                "category": ci_decision.category,
                "intent": ci_decision.intent,
                "action": ci_decision.action,
                "confidence": ci_decision.confidence,
                "sensitive": ci_decision.sensitive,
                "admin_alert": ci_decision.admin_alert,
                "has_photo": has_photo,
                "has_video": has_video,
                "would_reply": ci_decision.action in {"reply", "reply_and_admin_alert"},
                "would_react": bool(ci_decision.emoji),
                "would_alert_admin": ci_decision.admin_alert,
                "reason": ci_decision.reason,
            }
            log_community_intelligence_event(ci_doc)
            if settings.community_helper_log_only:
                logger.info(
                    "community_helper_log_only message_id=%s intent=%s action=%s sensitive=%s",
                    message.message_id,
                    ci_decision.intent,
                    ci_decision.action,
                    ci_decision.sensitive,
                )
            else:
                if (
                    getattr(settings, "community_reactions_enabled", False)
                    and ci_decision.emoji
                    and not ci_decision.sensitive
                    and not ci_decision.admin_alert
                ):
                    await safe_add_reaction(
                        bot=context.bot,
                        chat_id=message.chat_id,
                        message_id=message.message_id,
                        emoji=ci_decision.emoji,
                        flow="community_helper",
                    )

            if not settings.community_helper_log_only and settings.community_faq_reply_enabled:
                now = normalize_utc_datetime(getattr(message, "date", None)) or utc_now()
                intent = ci_decision.intent or ""
                can_send = (
                    ci_decision.action == "reply"
                    and bool(intent)
                    and intent in settings.community_live_allowed_intents
                    and bool(ci_decision.reply)
                    and not ci_decision.sensitive
                    and not ci_decision.admin_alert
                )
                suppress_reason = None
                if not can_send:
                    if not intent or intent not in settings.community_live_allowed_intents:
                        suppress_reason = "not_allowed_intent"
                    elif not ci_decision.reply:
                        suppress_reason = "no_reply"
                    elif ci_decision.sensitive:
                        suppress_reason = "sensitive"
                    else:
                        suppress_reason = "disabled"
                if intent in _BLOCKED_LIVE_INTENTS or intent.startswith(_BLOCKED_LIVE_INTENT_PREFIXES):
                    can_send = False
                    suppress_reason = "not_allowed_intent"

                if can_send:
                    try:
                        if count_recent_community_helper_replies(
                            since=now - timedelta(seconds=settings.community_reply_fingerprint_cooldown_sec),
                            chat_id=message.chat_id,
                            fingerprint=ci_decision.fingerprint,
                        ) > 0:
                            can_send = False
                            suppress_reason = "duplicate_fingerprint"
                        elif count_recent_community_helper_replies(
                            since=now - timedelta(seconds=settings.community_reply_user_cooldown_sec),
                            user_id=message.from_user.id if message.from_user else None,
                        ) > 0:
                            can_send = False
                            suppress_reason = "user_cooldown"
                        elif count_recent_community_helper_replies(
                            since=now - timedelta(minutes=10),
                            chat_id=message.chat_id,
                        ) >= settings.community_reply_chat_cap_10m:
                            can_send = False
                            suppress_reason = "chat_cap"
                        elif count_recent_community_helper_replies(
                            since=now - timedelta(
                                minutes=_setting_number(settings, "community_reply_min_gap_minutes", 60, minimum=0)
                            ),
                            chat_id=message.chat_id,
                        ) > 0:
                            can_send = False
                            suppress_reason = "min_gap"
                            logger.info(
                                "reply_skipped_min_gap chat_id=%s message_id=%s intent=%s min_gap_minutes=%s",
                                message.chat_id,
                                message.message_id,
                                intent,
                                _setting_number(settings, "community_reply_min_gap_minutes", 60, minimum=0),
                            )
                        elif count_recent_community_helper_replies(
                            since=now - timedelta(days=1),
                            chat_id=message.chat_id,
                        ) >= _setting_number(settings, "community_reply_daily_cap", 10, minimum=0):
                            can_send = False
                            suppress_reason = "daily_cap"
                            logger.info(
                                "reply_skipped_daily_cap chat_id=%s message_id=%s intent=%s daily_cap=%s",
                                message.chat_id,
                                message.message_id,
                                intent,
                                _setting_number(settings, "community_reply_daily_cap", 10, minimum=0),
                            )
                    except Exception:
                        can_send = False
                        suppress_reason = "disabled"
                        logger.warning("community_helper_live_db_check_failed message_id=%s", message.message_id, exc_info=True)

                if can_send:
                    reply_probability = _setting_number(
                        settings, "community_reply_probability", 0.2, minimum=0.0, maximum=1.0
                    )
                    if random.random() >= reply_probability:
                        can_send = False
                        suppress_reason = "probability"
                        logger.info(
                            "reply_skipped_probability chat_id=%s message_id=%s intent=%s probability=%s",
                            message.chat_id,
                            message.message_id,
                            intent,
                            reply_probability,
                        )
                    else:
                        logger.info(
                            "reply_allowed chat_id=%s message_id=%s intent=%s probability=%s",
                            message.chat_id,
                            message.message_id,
                            intent,
                            reply_probability,
                        )

                reply_sent = False
                button_count = len(ci_decision.buttons or [])
                try:
                    if can_send:
                        reply_markup = None
                        if ci_decision.buttons:
                            rows = []
                            for btn in ci_decision.buttons:
                                btn_text, btn_url = _community_button_text_url(btn)
                                if btn_text and btn_url and (
                                    getattr(settings, "official_channel_cta_enabled", False)
                                    or not _is_official_channel_button(btn_text, btn_url)
                                ):
                                    rows.append([InlineKeyboardButton(text=btn_text, url=btn_url)])
                            if rows:
                                reply_markup = InlineKeyboardMarkup(rows)
                        await message.reply_text(ci_decision.reply, reply_markup=reply_markup)
                        reply_sent = True
                    log_community_helper_reply_event({
                        "created_at": now,
                        "chat_id": message.chat_id,
                        "message_id": message.message_id,
                        "user_id": message.from_user.id if message.from_user else None,
                        "username": message.from_user.username if message.from_user else None,
                        "fingerprint": ci_decision.fingerprint,
                        "intent": ci_decision.intent,
                        "category": ci_decision.category,
                        "reply_sent": reply_sent,
                        "suppressed": not reply_sent,
                        "suppress_reason": None if reply_sent else suppress_reason,
                        "reply_text_sample": (ci_decision.reply or "")[:200],
                        "button_count": button_count,
                    })
                except Exception:
                    logger.warning("community_helper_live_reply_failed message_id=%s", message.message_id, exc_info=True)
        except Exception:
            logger.warning("community_helper_classification_failed message_id=%s", message.message_id, exc_info=True)

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

    # Stage 2 AI decision only for ambiguous/non-deterministic path.
    ai_path_used = False
    path_used = "deterministic"
    budget_state = "none"
    moderation_state = "none"
    reply_sent = False
    downgrade_applied = False
    category_before = category
    if should_run_ai_decision(settings=settings, text=text, rule_category=category, rule_confidence=confidence):
        ai_path_used = True
        try:
            runtime = _get_ai_runtime(settings)
            if runtime is None:
                raise RuntimeError("ai_runtime_unavailable")
            client, ai_decision_service, ai_reply_service, reply_policy = runtime
            priority = category in set(settings.ai_priority_categories)
            decision_budget = ai_budget_service.allow_decision(
                chat_id=message.chat_id,
                max_per_minute=settings.ai_max_decisions_per_minute,
                max_per_chat_per_hour=settings.ai_max_decisions_per_chat_per_hour,
                priority=priority,
            )
            budget_state = decision_budget.state
            if not decision_budget.allowed:
                decision_reason = f"ai_decision_skipped_due_to_budget:{decision_budget.reason}"
                action = "ignore" if not priority else action
                raise RuntimeError("ai_decision_budget_block")

            few_shot = get_few_shot_examples(category, limit=5) if category != "unknown" else []
            ai_decision = ai_decision_service.decide(text, few_shot_examples=few_shot or None)
            policy = reply_policy.evaluate(ai_decision)
            decision_reason = f"ai:{policy.reason}"
            category = ai_decision.category
            confidence = ai_decision.confidence
            action = "auto_reply" if policy.should_send else "ignore"
            suggested_reply = ""
            path_used = policy.mode
            if action == "ignore":
                logger.info("ai_no_reply_due_to_policy message_id=%s reason=%s", message.message_id, policy.reason)

            if policy.should_send and settings.enable_ai_moderation:
                moderation_input = client.moderate(text)
                if moderation_input:
                    action = "ignore"
                    decision_reason = "ai:moderation_input_block"
                    moderation_state = "input_blocked"
                    logger.info("ai_blocked_by_moderation message_id=%s", message.message_id)
                else:
                    moderation_state = "input_ok"

            selected_seed = None
            if policy.seed_candidates:
                selected_seed = seed_rotation_service.pick_seed(
                    chat_id=message.chat_id,
                    category=policy.category,
                    seeds=policy.seed_candidates,
                    repeat_window_seconds=settings.ai_seed_repeat_window_seconds,
                    max_seed_reuse_per_window=settings.ai_max_seed_reuse_per_window,
                )
                policy.selected_seed = selected_seed

            generation_allowed = (
                action == "auto_reply"
                and policy.should_send
                and policy.mode == "rewrite"
                and settings.enable_ai_generation
                and settings.ai_generation_rewrite_mode
                and selected_seed is not None
            )
            if generation_allowed:
                generation_budget = ai_budget_service.allow_generation(
                    max_per_minute=settings.ai_max_generations_per_minute,
                    allow_downgrade=settings.ai_enable_budget_downgrade,
                    priority=priority,
                )
                budget_state = generation_budget.state
                if generation_budget.state == "downgrade":
                    suggested_reply = selected_seed.text
                    decision_reason = "ai_generation_downgraded_to_seed"
                    path_used = "seed"
                    downgrade_applied = True
                    logger.info("ai_generation_downgraded_to_seed message_id=%s", message.message_id)
                elif not generation_budget.allowed:
                    action = "ignore"
                    decision_reason = f"ai_generation_blocked_due_to_budget:{generation_budget.reason}"
                else:
                    if len((selected_seed.text or "").strip()) < 16:
                        suggested_reply = selected_seed.text
                        path_used = "seed"
                        downgrade_applied = True
                        decision_reason = "ai_generation_short_seed_fallback_to_seed"
                    else:
                        try:
                            ai_reply = ai_reply_service.generate(
                                decision=ai_decision,
                                user_text=text,
                                seed_text=selected_seed.text,
                                max_chars=settings.ai_max_reply_chars,
                            )
                        except Exception:
                            logger.exception("AI rewrite generation failed; falling back to seed message_id=%s", message.message_id)
                            suggested_reply = selected_seed.text
                            path_used = "seed"
                            downgrade_applied = True
                            decision_reason = "ai_generation_error_fallback_to_seed"
                        else:
                            if ai_reply:
                                if settings.enable_ai_moderation:
                                    moderation_reply = client.moderate(ai_reply)
                                    if moderation_reply:
                                        action = "ignore"
                                        decision_reason = "ai:moderation_reply_block"
                                        moderation_state = "output_blocked"
                                        logger.info("ai_blocked_by_moderation message_id=%s", message.message_id)
                                    else:
                                        suggested_reply = ai_reply
                                        moderation_state = "output_ok"
                                        path_used = "rewrite"
                                else:
                                    suggested_reply = ai_reply
                                    path_used = "rewrite"
                            else:
                                suggested_reply = selected_seed.text
                                path_used = "seed"
                                downgrade_applied = True
                                decision_reason = "ai_generation_empty_fallback_to_seed"
            elif action == "auto_reply" and selected_seed is not None:
                suggested_reply = selected_seed.text
                path_used = "seed"

            if action == "auto_reply" and selected_seed is not None and settings.enable_seed_rotation_memory:
                seed_rotation_service.mark_used(
                    chat_id=message.chat_id,
                    category=policy.category,
                    seed_key=selected_seed.key,
                )
        except Exception:
            if decision_reason.startswith("ai_decision_skipped_due_to_budget"):
                logger.info("ai_decision_skipped_due_to_budget message_id=%s", message.message_id)
            else:
                action = "ignore"
                decision_reason = "ai_failure"
                logger.exception("AI decision/generation failed message_id=%s", message.message_id)

    logger.info(
        "Classified message_id=%s category=%s action=%s confidence=%s path=%s budget_state=%s moderation_state=%s",
        message.message_id,
        category,
        action,
        confidence,
        path_used if ai_path_used else "deterministic",
        budget_state,
        moderation_state,
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
        elif category == "comeback_campaign":
            emoji = get_reaction(category)
            if emoji and reaction_cooldown.allow(
                chat_id=message.chat_id,
                category="comeback_campaign",
                cooldown_seconds=settings.comeback_reaction_cooldown_seconds,
            ):
                await safe_add_reaction(
                    bot=context.bot,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    emoji=emoji,
                    flow="comeback_campaign",
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
                _det_seeds = SEED_REPLIES.get(category, [])
                _det_seed = seed_rotation_service.pick_seed(
                    chat_id=message.chat_id,
                    category=category,
                    seeds=_det_seeds,
                    repeat_window_seconds=settings.ai_seed_repeat_window_seconds,
                    max_seed_reuse_per_window=settings.ai_max_seed_reuse_per_window,
                ) if _det_seeds else None
                if _det_seed:
                    base = RESPONSES.get(category, {})
                    if isinstance(base, dict) and base.get("button_text"):
                        reply_payload = {
                            "text": _det_seed.text,
                            "button_text": base.get("button_text"),
                            "button_url": base.get("button_url"),
                        }
                        allow_button = True
                    else:
                        reply_payload = _det_seed.text
                        allow_button = False
                    if settings.enable_seed_rotation_memory:
                        seed_rotation_service.mark_used(
                            chat_id=message.chat_id,
                            category=category,
                            seed_key=_det_seed.key,
                        )
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
                official_channel_cta_enabled=getattr(settings, "official_channel_cta_enabled", False),
            )
            if reply_text:
                logger.info("Auto reply triggered for message_id=%s category=%s", message.message_id, category)
                kwargs = {}
                if settings.enable_threaded_replies:
                    kwargs["reply_to_message_id"] = message.message_id
                if reply_markup:
                    kwargs["reply_markup"] = reply_markup
                if category == "new_user":
                    kwargs["parse_mode"] = "HTML"
                await message.reply_text(reply_text, **kwargs)
                reply_sent = True
                if path_used == "seed":
                    logger.info("seed_reply_sent message_id=%s category=%s", message.message_id, category)
                if path_used == "rewrite":
                    logger.info("ai_rewritten_reply_sent message_id=%s category=%s", message.message_id, category)
                if path_used == "deterministic":
                    logger.info("deterministic_reply_sent message_id=%s category=%s", message.message_id, category)
    log_message(
        category,
        update,
        decision={
            "category": category,
            "action": action,
            "confidence": confidence,
            "reason": decision_reason,
            "path": path_used if ai_path_used else "deterministic",
            "category_before": category_before,
            "category_after": category,
            "ai_used": ai_path_used,
            "budget_state": budget_state,
            "moderation_state": moderation_state,
            "reply_sent": reply_sent,
            "downgrade_applied": downgrade_applied,
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
                f"Suggested reply: {suggestion}\n\n"
                f"Reply /approve, /reject, or /correct <category> to give feedback."
            )
            sent = await context.bot.send_message(chat_id=settings.admin_chat_id, text=admin_text)
            log_suggestion(
                bot_message_id=sent.message_id,
                original_message_id=message.message_id,
                chat_id=message.chat_id,
                original_text=text,
                suggested_reply=suggestion,
                category=category,
            )


async def _admin_feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, approved: bool) -> None:
    settings = get_settings()
    message = update.message
    if message is None:
        return
    if not settings.admin_chat_id or message.chat_id != settings.admin_chat_id:
        return
    replied_to = message.reply_to_message
    if replied_to is None:
        await message.reply_text("Reply to a suggestion message to give feedback.")
        return
    correct_category = context.args[0] if context.args else None
    found = log_feedback(
        bot_message_id=replied_to.message_id,
        approved=approved,
        correct_category=correct_category,
    )
    if found:
        label = "approved" if approved else "rejected"
        cat_note = f" (corrected to {correct_category})" if correct_category else ""
        await message.reply_text(f"Feedback recorded: {label}{cat_note}. The bot will learn from this.")
        logger.info("Feedback recorded bot_message_id=%s approved=%s correct_category=%s", replied_to.message_id, approved, correct_category)
    else:
        await message.reply_text("Could not find the suggestion. Make sure you reply to the bot's suggestion message.")


async def approve_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _admin_feedback_handler(update, context, approved=True)


async def reject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _admin_feedback_handler(update, context, approved=False)


async def correct_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _admin_feedback_handler(update, context, approved=True)


def parse_report_window(arg: str | None) -> tuple[timedelta, str]:
    token = (arg or "").strip().lower()
    if token == "6h":
        return timedelta(hours=6), "Last 6h"
    if token == "24h" or token == "":
        return timedelta(hours=24), "Last 24h"
    if token == "7d":
        return timedelta(days=7), "Last 7d"
    return timedelta(hours=24), "Last 24h"


def _truncate_sample(value: str | None, limit: int = 80) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_community_helper_report(window_label: str, stats: dict) -> str:
    if not stats.get("total", 0):
        return f"📊 Community Helper Report — {window_label}\n\nNo telemetry found for this window."
    lines = [
        f"📊 Community Helper Report — {window_label}",
        "",
        f"Total classified: {stats.get('total', 0)}",
        f"Would reply: {stats.get('would_reply', 0)}",
        f"Would react: {stats.get('would_react', 0)}",
        f"Would alert admin: {stats.get('would_alert_admin', 0)}",
        f"Sensitive: {stats.get('sensitive', 0)}",
        f"Unknown: {stats.get('unknown', 0)}",
        f"Unknown rate: {stats.get('unknown_rate', 0.0):.1f}%",
        "",
        "Top intents:",
    ]
    for i, item in enumerate(stats.get("top_intents", [])[:10], start=1):
        lines.append(f"{i}. {item.get('_id') or 'none'} — {item.get('count', 0)}")
    lines.append("")
    lines.append("Top categories:")
    for i, item in enumerate(stats.get("top_categories", [])[:10], start=1):
        lines.append(f"{i}. {item.get('_id') or 'none'} — {item.get('count', 0)}")
    lines.append("")
    lines.append("Top duplicate messages:")
    for i, item in enumerate(stats.get("top_duplicates", [])[:10], start=1):
        lines.append(
            f"{i}. \"{escape(_truncate_sample(item.get('sample_text')))}\" — {item.get('count', 0)} times — {item.get('intent') or item.get('category') or 'unknown'}"
        )
    lines.append("")
    lines.append("Sensitive samples:")
    for item in stats.get("sensitive_samples", [])[:5]:
        lines.append(f"- {item.get('intent') or item.get('category') or 'unknown'}: \"{escape(_truncate_sample(item.get('text_sample')))}\"")
    lines.append("")
    lines.append("Unknown samples:")
    for item in stats.get("unknown_samples", [])[:5]:
        lines.append(f"- \"{escape(_truncate_sample(item.get('text_sample')))}\"")
    return "\n".join(lines)[:3900]


def _is_admin_message(message, settings) -> bool:
    if message is None:
        return False
    if settings.admin_chat_id and message.chat_id == settings.admin_chat_id:
        return True
    return False


async def community_helper_report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    message = update.message
    if message is None:
        return
    if not _is_admin_message(message, settings):
        await message.reply_text("This command is admin-only.")
        return
    window, label = parse_report_window(context.args[0] if context.args else None)
    since = utc_now() - window
    try:
        stats = aggregate_community_helper_events(since=since)
    except Exception:
        logger.warning("community_helper_report_failed", exc_info=True)
        await message.reply_text("Could not generate community helper report right now.")
        return
    await message.reply_text(build_community_helper_report(label, stats), parse_mode="HTML")


def setup_application():
    settings = get_settings()
    _get_ai_runtime(settings)
    application = ApplicationBuilder().token(settings.telegram_token).build()
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members_handler))
    application.add_handler(MessageHandler(filters.CAPTION, cyrillic_caption_moderation_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    application.add_handler(CommandHandler("approve", approve_handler))
    application.add_handler(CommandHandler("reject", reject_handler))
    application.add_handler(CommandHandler("correct", correct_handler))
    application.add_handler(CommandHandler("community_helper_report", community_helper_report_handler))
    register_engagement_topic_job(application)
    register_engagement_jobs(application)
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
