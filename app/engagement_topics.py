import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from .config import get_settings
from .db import get_db
from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)
TOPIC_TYPE = "slot_behavior_topic"
BLOCKED_PHRASES = [
    "deposit", "top up", "sure win", "guaranteed", "claim now", "bet more", "go play", "jackpot today",
    "bonus", "free credit", "voucher", "promo", "promotion", "cashback", "register now",
]
HARD_WORDS = [
    "bankroll", "discipline", "volatility", "strategy", "probability", "session management",
    "responsible gaming framework", "optimization", "behavior pattern",
]
LOCK_DURATION_MINUTES = 10
SEED_FALLBACKS: Dict[str, str] = {
    "stop-loss behavior": "What makes you stop for the day?",
    "fast spin vs manual spin": "Fast spin or normal spin — which one you like?",
    "cold streak habits": "Cold game, stop or change game?",
    "chasing after losses": "After losing, rest or try again?",
    "leaving after profit": "After small win, stop or continue?",
    "feature buy opinion": "Feature buy: good or trap?",
    "best timing to play": "Late night really luckier?",
    "dead spin frustration": "How many dead spins before you stop?",
    "tilt control": "After losing, rest or try again?",
    "bankroll discipline": "Long play or short play — which better?",
    "switching games too fast": "One game long time, or keep changing?",
    "lucky pattern superstition": "Do you believe lucky timing?",
    "big win behavior": "Big win happen, stop first or continue?",
    "small win discipline": "Win small small, still happy or not enough?",
    "session duration habits": "Long play or short play — which better?",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _history_col():
    settings = get_settings()
    return get_db()["engagement_topic_history"], settings


def _lock_col():
    return get_db()["engagement_topic_locks"]


def _as_aware_utc(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _acquire_send_lock(chat_id: int, now: datetime) -> bool:
    lock_id = f"{TOPIC_TYPE}:{chat_id}"
    try:
        doc = _lock_col().find_one_and_update(
            {
                "_id": lock_id,
                "$or": [
                    {"locked_until": {"$lte": now}},
                    {"locked_until": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "locked_until": now + timedelta(minutes=LOCK_DURATION_MINUTES),
                    "updated_at": now,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return bool(doc)
    except DuplicateKeyError:
        return False
    except PyMongoError:
        logger.exception("[ENGAGEMENT_TOPIC][ERROR] lock_acquire_failed")
        return False


def _release_send_lock(chat_id: int) -> None:
    lock_id = f"{TOPIC_TYPE}:{chat_id}"
    now = _utcnow()
    try:
        _lock_col().update_one({"_id": lock_id}, {"$set": {"locked_until": now, "updated_at": now}})
    except PyMongoError:
        logger.exception("[ENGAGEMENT_TOPIC][ERROR] lock_release_failed")


def ensure_engagement_topic_indexes() -> None:
    col, _ = _history_col()
    col.create_index([("sent_at", DESCENDING)])
    col.create_index([("type", 1), ("seed", 1), ("sent_at", DESCENDING)])
    col.create_index([("type", 1), ("text", 1), ("sent_at", DESCENDING)])
    col.create_index([("chat_id", 1), ("sent_at", DESCENDING)])
    _lock_col().create_index([("locked_until", 1)])


def _active_campaign_or_drop() -> bool:
    logger.info("[ENGAGEMENT_TOPIC][SKIP_CHECK] active_drop_or_campaign helper_not_found")
    return False


def _sanitize_question(text: str, max_chars: int, require_question: bool = True) -> Tuple[Optional[str], Optional[str]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None, "empty"
    if "\n\n" in cleaned:
        return None, "newline_spam"
    lowered = cleaned.lower()
    words = [w for w in re.findall(r"[A-Za-z']+", cleaned)]
    if len(words) > 18:
        return None, "too_many_words"
    if len(cleaned) > max_chars:
        return None, "too_long"
    if re.search(r"(?:https?://|www\.)", cleaned, flags=re.IGNORECASE):
        return None, "contains_url"
    for hard in HARD_WORDS:
        if hard in lowered:
            return None, f"hard_word:{hard}"
    if words:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if avg_word_len > 6:
            return None, "too_complex"
    for blocked in BLOCKED_PHRASES:
        if blocked in lowered:
            return None, f"blocked_phrase:{blocked}"
    if require_question and "?" not in cleaned:
        return None, "not_question"
    return cleaned, None


def _pick_seed(col, seed_cooldown_days: int) -> str:
    seeds = list(SEED_FALLBACKS.keys())
    cutoff = _utcnow() - timedelta(days=seed_cooldown_days)
    recent = col.find({"type": TOPIC_TYPE, "status": "sent", "sent_at": {"$gte": cutoff}}, {"seed": 1})
    recent_set = {d.get("seed") for d in recent if d.get("seed")}
    available = [s for s in seeds if s not in recent_set]
    if available:
        return random.choice(available)
    oldest = col.find_one({"type": TOPIC_TYPE, "status": "sent"}, sort=[("sent_at", 1)])
    if oldest and oldest.get("seed") in seeds:
        return oldest["seed"]
    return random.choice(seeds)


def _generate_ai_question(seed: str, model: str) -> Optional[str]:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    client = OpenAIClient(api_key=settings.openai_api_key)
    if not client.enabled:
        return None
    prompt = (
        "Generate 1 short Telegram group engagement question.\\n\\n"
        "Rules:\\n"
        "- Topic must be about slot player behavior, slot habits, session discipline, or community opinion.\\n"
        "- Use very simple English.\\n"
        "- Use short words.\\n"
        "- Keep primary-school level English.\\n"
        "- Max 12 words if possible. Hard max 18 words.\\n"
        "- No long sentence.\\n"
        "- No corporate tone.\\n"
        "- No complex words.\\n"
        "- Tone casual, human, local Telegram style.\\n"
        "- Ask only 1 question.\\n"
        "- No promotion.\\n"
        "- No bonus/voucher mention.\\n"
        "- No gambling encouragement.\\n"
        "- Avoid go play, deposit, top up, bet more, sure win, guaranteed, claim now, jackpot today.\\n"
        "- Avoid words: bankroll, discipline, volatility, strategy, probability, session management, responsible gaming framework, optimization, behavior pattern.\\n"
        "- Do not mention brand name.\\n"
        "- Make it opinion-based and easy to reply to.\\n"
        "- Return only the question text, no quotes, no explanation.\\n\\n"
        f"Seed topic: {seed}"
    )
    return client.generate_reply(model=model, instructions=prompt, input_text=seed)


async def run_engagement_topic_job(context=None) -> None:
    try:
        col, settings = _history_col()
        enabled = bool(getattr(settings, "engagement_topics_enabled", False))
        if not enabled:
            logger.info("[ENGAGEMENT_TOPIC][SKIP] disabled")
            return
        chat_id = getattr(settings, "engagement_topic_chat_id", None)
        if not chat_id:
            logger.info("[ENGAGEMENT_TOPIC][SKIP] missing_chat_id")
            return
        if _active_campaign_or_drop():
            logger.info("[ENGAGEMENT_TOPIC][SKIP] active_drop_or_campaign")
            return

        now = _utcnow()
        if not _acquire_send_lock(chat_id, now):
            logger.info("[ENGAGEMENT_TOPIC][SKIP] lock_not_acquired")
            return
        last_sent = col.find_one({"type": TOPIC_TYPE, "status": "sent", "chat_id": chat_id}, sort=[("sent_at", -1)])
        min_interval_hours = int(getattr(settings, "engagement_topic_min_interval_hours", 48))
        try:
            if last_sent and last_sent.get("sent_at"):
                last_sent_at = _as_aware_utc(last_sent["sent_at"])
                if last_sent_at and now - last_sent_at < timedelta(hours=min_interval_hours):
                    logger.info("[ENGAGEMENT_TOPIC][SKIP] interval_not_reached last_sent_at=%s", last_sent_at)
                    return

            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            daily_cap = int(getattr(settings, "engagement_topic_daily_cap", 1))
            day_count = col.count_documents({"type": TOPIC_TYPE, "status": "sent", "chat_id": chat_id, "sent_at": {"$gte": day_start}}, limit=daily_cap + 1)
            if day_count >= daily_cap:
                logger.info("[ENGAGEMENT_TOPIC][SKIP] daily_cap_reached count=%s", day_count)
                return

            if bool(getattr(settings, "engagement_topic_require_quiet", False)):
                logger.info("[ENGAGEMENT_TOPIC][SKIP_CHECK] quiet_window_unavailable")

            seed = _pick_seed(col, int(getattr(settings, "engagement_topic_seed_cooldown_days", 30)))
            max_chars = int(getattr(settings, "engagement_topic_max_chars", 120))
            question = None
            source = "fallback"
            if bool(getattr(settings, "engagement_topic_ai_enabled", False)):
                try:
                    question = _generate_ai_question(seed, getattr(settings, "engagement_topic_openai_model", settings.openai_generation_model))
                    question, reason = _sanitize_question(question or "", max_chars=max_chars, require_question=True)
                    if question is None:
                        logger.info("[ENGAGEMENT_TOPIC][AI_REJECT] reason=%s", reason)
                except Exception as exc:
                    logger.exception("[ENGAGEMENT_TOPIC][ERROR] ai_generation_failed error=%s", exc)
                    question = None

            if not question:
                fallback_text = SEED_FALLBACKS[seed]
                question, reason = _sanitize_question(fallback_text, max_chars=max_chars, require_question=False)
                if not question:
                    logger.info("[ENGAGEMENT_TOPIC][ERROR] invalid_fallback reason=%s", reason)
                    return
                source = "fallback"
            else:
                source = "ai"

            text_cd_cutoff = now - timedelta(days=int(getattr(settings, "engagement_topic_text_cooldown_days", 60)))
            dup = col.find_one({"type": TOPIC_TYPE, "status": "sent", "chat_id": chat_id, "text": question, "sent_at": {"$gte": text_cd_cutoff}}, {"_id": 1})
            if dup:
                logger.info("[ENGAGEMENT_TOPIC][SKIP] duplicate_text_cooldown")
                return

            logger.info("[ENGAGEMENT_TOPIC][SEND_ATTEMPT] seed=%s source=%s", seed, source)
            bot = getattr(context, "bot", None) if context else None
            if bot is None:
                logger.info("[ENGAGEMENT_TOPIC][ERROR] bot_context_missing")
                return
            sent = await bot.send_message(chat_id=chat_id, text=question)
            col.insert_one({
                "type": TOPIC_TYPE,
                "seed": seed,
                "text": question,
                "source": source,
                "chat_id": chat_id,
                "sent_at": now,
                "message_id": getattr(sent, "message_id", None),
                "status": "sent",
                "skip_reason": None,
            })
            logger.info("[ENGAGEMENT_TOPIC][SENT] chat_id=%s message_id=%s seed=%s source=%s", chat_id, getattr(sent, "message_id", None), seed, source)
        finally:
            _release_send_lock(chat_id)
    except Exception as exc:
        logger.exception("[ENGAGEMENT_TOPIC][ERROR] %s", exc)


def register_engagement_topic_job(application) -> None:
    settings = get_settings()
    if not getattr(settings, "engagement_topics_enabled", False):
        return
    ensure_engagement_topic_indexes()
    interval = int(getattr(settings, "engagement_topic_scheduler_interval_hours", 6))
    application.job_queue.run_repeating(run_engagement_topic_job, interval=timedelta(hours=interval), first=30, name="engagement_topic_job")
