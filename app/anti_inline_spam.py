import logging
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

try:
    from telegram.error import TelegramError
except ImportError:
    TelegramError = Exception

logger = logging.getLogger(__name__)

PORN_KEYWORDS = {
    "nude",
    "nudes",
    "porn",
    "porno",
    "sex",
    "creampie",
    "schoolgirl",
    "archive",
    "onlyfans",
    "leaked",
    "xxx",
    "blowjob",
    "pussy",
    "hentai",
    "18+",
    "nsfw",
}


@dataclass(frozen=True)
class AntiInlineSpamDecision:
    matched: bool
    reasons: tuple[str, ...] = ()


def normalize_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@").lower()


def _iter_inline_buttons(reply_markup) -> Iterable:
    keyboard = getattr(reply_markup, "inline_keyboard", None) or []
    for row in keyboard:
        for button in row or []:
            yield button


def has_url_button(message) -> bool:
    reply_markup = getattr(message, "reply_markup", None)
    if not reply_markup:
        return False
    return any(bool(getattr(button, "url", None)) for button in _iter_inline_buttons(reply_markup))


def has_media(message) -> bool:
    return any(
        bool(getattr(message, field, None))
        for field in ("photo", "video", "animation", "document")
    )


def contains_porn_keyword(text: str | None) -> bool:
    lowered = (text or "").lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", lowered) for keyword in PORN_KEYWORDS)


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().strip(".")
    return host or None


def _domain_allowed(domain: str | None, allowed_domains: set[str]) -> bool:
    if not domain:
        return False
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)


def _entity_url(entity, text: str) -> str | None:
    url = getattr(entity, "url", None)
    if url:
        return url
    if getattr(entity, "type", None) != "url":
        return None
    offset = int(getattr(entity, "offset", 0) or 0)
    length = int(getattr(entity, "length", 0) or 0)
    if length <= 0:
        return None
    return text[offset : offset + length]


def contains_non_allowlisted_entity_url(message, *, allowed_domains: set[str]) -> bool:
    text_by_field = {
        "entities": getattr(message, "text", None) or "",
        "caption_entities": getattr(message, "caption", None) or "",
    }
    for entity_field, text in text_by_field.items():
        for entity in getattr(message, entity_field, None) or []:
            entity_type = getattr(entity, "type", None)
            if entity_type not in {"url", "text_link"}:
                continue
            domain = _domain_from_url(_entity_url(entity, text))
            if not _domain_allowed(domain, allowed_domains):
                return True
    return False


def is_allowlisted_sender(message, settings) -> bool:
    user = getattr(message, "from_user", None)
    if not user:
        return False
    username = normalize_username(getattr(user, "username", None))
    user_id = getattr(user, "id", None)
    if user_id in getattr(settings, "anti_inline_spam_allowed_user_ids", set()):
        return True
    if username and username in getattr(settings, "anti_inline_spam_allowed_usernames", set()):
        return True
    if (
        getattr(user, "is_bot", False)
        and username
        and username in getattr(settings, "anti_inline_spam_allowed_bot_usernames", set())
    ):
        return True
    return False


def detect_anti_inline_spam(message, settings, *, text: str | None = None) -> AntiInlineSpamDecision:
    if is_allowlisted_sender(message, settings):
        return AntiInlineSpamDecision(False)

    reasons: list[str] = []
    user = getattr(message, "from_user", None)
    username = normalize_username(getattr(user, "username", None))
    allowed_domains = getattr(settings, "anti_inline_spam_allowed_domains", {"t.me", "telegram.me"})

    if username.endswith("bot"):
        reasons.append("username_endswith_bot")
    if getattr(message, "via_bot", None):
        reasons.append("via_bot")
    if has_url_button(message):
        reasons.append("url_button")
    if has_media(message) and getattr(message, "reply_markup", None):
        reasons.append("media_with_reply_markup")
    if contains_porn_keyword(text):
        reasons.append("porn_keyword")
    if contains_non_allowlisted_entity_url(message, allowed_domains=allowed_domains):
        reasons.append("non_allowlisted_entity_url")

    return AntiInlineSpamDecision(bool(reasons), tuple(reasons))


async def process_anti_inline_spam(
    update,
    context,
    settings,
    *,
    is_group_message,
    sender_is_admin_or_owner,
    text_extractor,
) -> bool:
    message = getattr(update, "message", None)
    if message is None or not getattr(settings, "anti_inline_spam_enabled", False):
        return False
    if not is_group_message(message):
        return False

    allowed_group_ids = getattr(settings, "anti_inline_spam_group_ids", set())
    if allowed_group_ids and message.chat_id not in allowed_group_ids:
        return False
    if is_allowlisted_sender(message, settings):
        return False
    if await sender_is_admin_or_owner(message, context):
        return False

    decision = detect_anti_inline_spam(message, settings, text=text_extractor(message))
    if not decision.matched:
        return False

    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    logger.warning(
        "[ANTI_INLINE_SPAM_MATCH] dry_run=%s chat_id=%s message_id=%s user_id=%s username=%s reasons=%s",
        getattr(settings, "anti_inline_spam_dry_run", True),
        message.chat_id,
        message.message_id,
        user_id,
        getattr(user, "username", None),
        ",".join(decision.reasons),
    )

    alert_chat_id = getattr(settings, "anti_inline_spam_admin_alert_chat_id", None)
    if alert_chat_id:
        try:
            await context.bot.send_message(
                chat_id=alert_chat_id,
                text=(
                    "Anti-inline-spam match\n"
                    f"chat_id={message.chat_id} message_id={message.message_id}\n"
                    f"user_id={user_id} username={getattr(user, 'username', None)}\n"
                    f"reasons={','.join(decision.reasons)} dry_run={getattr(settings, 'anti_inline_spam_dry_run', True)}"
                ),
            )
        except TelegramError:
            logger.warning("[ANTI_INLINE_SPAM_ALERT_FAILED] chat_id=%s message_id=%s", message.chat_id, message.message_id, exc_info=True)
        except Exception:
            logger.exception("[ANTI_INLINE_SPAM_ALERT_FAILED] chat_id=%s message_id=%s", message.chat_id, message.message_id)

    if getattr(settings, "anti_inline_spam_dry_run", True):
        return False

    if getattr(settings, "anti_inline_spam_delete", True):
        try:
            await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
            logger.info("[ANTI_INLINE_SPAM_DELETE] chat_id=%s message_id=%s", message.chat_id, message.message_id)
        except TelegramError:
            logger.warning("[ANTI_INLINE_SPAM_DELETE_FAILED] chat_id=%s message_id=%s", message.chat_id, message.message_id, exc_info=True)
        except Exception:
            logger.exception("[ANTI_INLINE_SPAM_DELETE_FAILED] chat_id=%s message_id=%s", message.chat_id, message.message_id)

    if getattr(settings, "anti_inline_spam_ban", True) and user_id is not None:
        try:
            await context.bot.ban_chat_member(chat_id=message.chat_id, user_id=user_id)
            logger.info("[ANTI_INLINE_SPAM_BAN] chat_id=%s user_id=%s", message.chat_id, user_id)
        except TelegramError:
            logger.warning("[ANTI_INLINE_SPAM_BAN_FAILED] chat_id=%s user_id=%s", message.chat_id, user_id, exc_info=True)
        except Exception:
            logger.exception("[ANTI_INLINE_SPAM_BAN_FAILED] chat_id=%s user_id=%s", message.chat_id, user_id)

    return True
