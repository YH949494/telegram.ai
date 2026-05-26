import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from inspect import signature
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from pymongo import DESCENDING

from .config import get_settings
from .db import get_db

logger = logging.getLogger(__name__)

PROMPT_EMOJI_VOTE = "emoji_vote"
PROMPT_AB_POLL = "ab_poll"
PROMPT_ONE_WORD = "one_word"
PROMPT_REVIVE = "revive"


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    prompt_type: str
    text: Optional[str] = None
    question: Optional[str] = None
    options: Optional[List[str]] = None


PROMPTS: List[Prompt] = [
    Prompt("emoji_energy", PROMPT_EMOJI_VOTE, text="Today energy level?\n🔥 = strong\n😴 = tired\n💀 = barely alive"),
    Prompt("emoji_luck_check", PROMPT_EMOJI_VOTE, text="Tonight luck check:\n🍀 lucky\n🤡 risky\n😎 steady"),
    Prompt("emoji_mood", PROMPT_EMOJI_VOTE, text="Current mood?\n🔥 / 😴 / 🫠"),
    Prompt("emoji_session_mood", PROMPT_EMOJI_VOTE, text="Today session mood?\n🔥 = confident\n😴 = tired\n🫠 = kena makan"),
    Prompt("emoji_chat_temp", PROMPT_EMOJI_VOTE, text="Chat temperature now?\n🔥 hot\n🧊 quiet\n👀 watching"),
    Prompt("emoji_tonight_vibe", PROMPT_EMOJI_VOTE, text="Tonight vibe?\n🍀 lucky\n🧠 careful\n😂 just testing"),
    Prompt("poll_spin_mode", PROMPT_AB_POLL, question="Fast spin or normal spin?", options=["Fast spin", "Normal spin"]),
    Prompt("poll_daypart", PROMPT_AB_POLL, question="Morning player or night player?", options=["Morning", "Night"]),
    Prompt("poll_big_win", PROMPT_AB_POLL, question="Tonight big win?", options=["Yes", "No"]),
    Prompt("poll_play_style", PROMPT_AB_POLL, question="Today play style?", options=["Careful", "YOLO"]),
    Prompt("poll_timing", PROMPT_AB_POLL, question="Better timing?", options=["Lunch break", "Midnight"]),
    Prompt("poll_community_mood", PROMPT_AB_POLL, question="Community mood today?", options=["Active", "Silent"]),
    Prompt("word_today", PROMPT_ONE_WORD, text="Describe today in 1 word 👇"),
    Prompt("word_mood", PROMPT_ONE_WORD, text="Drop 1 word for your current mood 👇"),
    Prompt("word_session", PROMPT_ONE_WORD, text="Your session today: 1 word only 👇"),
    Prompt("word_today_session", PROMPT_ONE_WORD, text="Today session in 1 word 👇"),
    Prompt("word_profit_recover_rest", PROMPT_ONE_WORD, text="Drop 1 word: profit, recover, or rest? 👇"),
    Prompt("word_luck", PROMPT_ONE_WORD, text="One word for today’s luck 👇"),
]

REVIVE_PROMPTS: List[Prompt] = [
    Prompt("revive_chat_check", PROMPT_REVIVE, text="Chat check 👀 who’s still here?"),
    Prompt("revive_silent_mode", PROMPT_REVIVE, text="Silent mode today ah? Drop an emoji 👇"),
    Prompt("revive_mood", PROMPT_REVIVE, text="Quick check: today mood 🔥 / 😴 / 🫠"),
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_tz(settings):
    try:
        return ZoneInfo(settings.engagement_timezone)
    except Exception:
        logger.warning("Invalid engagement timezone=%s; falling back to UTC", settings.engagement_timezone)
        return timezone.utc


def _date_key(now: datetime, settings) -> str:
    return now.astimezone(_get_tz(settings)).date().isoformat()


def _is_quiet_hours(now: datetime, settings) -> bool:
    if not settings.engagement_quiet_hours_enabled:
        return False
    start = int(settings.engagement_quiet_start_hour)
    end = int(settings.engagement_quiet_end_hour)
    if start == end:
        return False
    hour = now.astimezone(_get_tz(settings)).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def ensure_engagement_indexes() -> None:
    db = get_db()
    col = db["engagement_posts"]
    col.create_index([("chat_id", 1), ("created_at", -1)], background=True)
    col.create_index([("chat_id", 1), ("date_key", 1)], background=True)
    col.create_index([("chat_id", 1), ("prompt_id", 1), ("created_at", -1)], background=True)
    col.create_index([("source", 1), ("status", 1), ("created_at", -1)], background=True)
    activity = db["community_chat_activity"]
    activity.create_index([("chat_id", 1)], unique=True, background=True)
    activity.create_index([("updated_at", -1)], background=True)


def _get_eligible_prompt(chat_id: int, source: str, now: datetime) -> Prompt:
    db = get_db()
    col = db["engagement_posts"]
    pool = REVIVE_PROMPTS if source == "revive" else PROMPTS
    cutoff = now - timedelta(days=7)
    recent = list(
        col.find(
            {"chat_id": chat_id, "source": source, "status": "sent", "created_at": {"$gte": cutoff}},
            {"prompt_id": 1},
            sort=[("created_at", DESCENDING)],
            limit=200,
        )
    )
    recent_ids = {doc.get("prompt_id") for doc in recent}
    choices = [p for p in pool if p.prompt_id not in recent_ids]
    if not choices:
        choices = pool
    return random.choice(choices)


def _recent_sent_count(chat_id: int, date_key: str, source: Optional[str] = None) -> int:
    query: Dict[str, object] = {"chat_id": chat_id, "date_key": date_key, "status": "sent"}
    if source:
        query["source"] = source
    return get_db()["engagement_posts"].count_documents(query)


def _last_sent(chat_id: int, source: Optional[str] = None):
    query = {"chat_id": chat_id, "status": "sent"}
    if source:
        query["source"] = source
    return get_db()["engagement_posts"].find_one(query, sort=[("sent_at", -1)])


async def _send_prompt(context, chat_id: int, prompt: Prompt, settings):
    if settings.engagement_posts_dry_run:
        return "dry_run", None, None
    if prompt.prompt_type == PROMPT_AB_POLL and settings.engagement_native_polls_enabled:
        sent = await context.bot.send_poll(
            chat_id=chat_id,
            question=prompt.question,
            options=prompt.options,
            is_anonymous=False,
            allows_multiple_answers=False,
            disable_notification=settings.engagement_default_disable_notification,
        )
        return "sent", getattr(sent, "message_id", None), None
    text = prompt.text or prompt.question or ""
    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        disable_notification=settings.engagement_default_disable_notification,
    )
    return "sent", getattr(sent, "message_id", None), None


async def run_engagement_posts_tick(context=None) -> None:
    settings = get_settings()
    if not settings.engagement_posts_enabled:
        return
    if not settings.engagement_target_chat_ids:
        logger.info("[ENGAGEMENT][SKIP] no_target_chats")
        return
    now = _utcnow()
    if _is_quiet_hours(now, settings):
        logger.info("[ENGAGEMENT][SKIP] quiet_hours")
        return
    date_key = _date_key(now, settings)
    for chat_id in settings.engagement_target_chat_ids:
        if _recent_sent_count(chat_id, date_key) >= settings.engagement_daily_max_posts:
            continue
        last = _last_sent(chat_id, source="scheduled")
        if last and last.get("sent_at") and now - last["sent_at"] < timedelta(minutes=settings.engagement_min_gap_minutes):
            continue
        prompt = _get_eligible_prompt(chat_id, "scheduled", now)
        await _attempt_send(context, chat_id, prompt, settings, source="scheduled", now=now, date_key=date_key)


async def run_engagement_inactivity_revive_tick(context=None) -> None:
    settings = get_settings()
    if not settings.engagement_posts_enabled or not settings.engagement_inactivity_revive_enabled:
        return
    if not settings.engagement_target_chat_ids:
        return
    now = _utcnow()
    if _is_quiet_hours(now, settings):
        logger.info("[ENGAGEMENT][REVIVE_SKIP] quiet_hours")
        return
    date_key = _date_key(now, settings)
    activity_col = get_db()["community_chat_activity"]
    for chat_id in settings.engagement_target_chat_ids:
        if _recent_sent_count(chat_id, date_key) >= settings.engagement_daily_max_posts:
            continue
        if _recent_sent_count(chat_id, date_key, source="revive") >= settings.engagement_revive_daily_max_posts:
            continue
        act = activity_col.find_one({"chat_id": chat_id}) or {}
        last_msg = act.get("last_message_at")
        if not last_msg or now - last_msg < timedelta(minutes=settings.engagement_inactivity_minutes):
            continue
        last_revive = act.get("last_revive_post_at")
        if last_revive and now - last_revive < timedelta(minutes=settings.engagement_revive_cooldown_minutes):
            continue
        prompt = _get_eligible_prompt(chat_id, "revive", now)
        await _attempt_send(context, chat_id, prompt, settings, source="revive", now=now, date_key=date_key)


async def _attempt_send(context, chat_id: int, prompt: Prompt, settings, *, source: str, now: datetime, date_key: str) -> None:
    post_col = get_db()["engagement_posts"]
    activity_col = get_db()["community_chat_activity"]
    status = "failed"
    msg_id = None
    err = None
    try:
        status, msg_id, err = await _send_prompt(context, chat_id, prompt, settings)
    except Exception as exc:
        err = str(exc)
        logger.warning("[ENGAGEMENT][SEND_FAIL] chat_id=%s source=%s prompt_id=%s", chat_id, source, prompt.prompt_id, exc_info=True)

    doc = {
        "chat_id": chat_id,
        "prompt_id": prompt.prompt_id,
        "prompt_type": prompt.prompt_type,
        "text": prompt.text,
        "question": prompt.question,
        "options": prompt.options,
        "source": source,
        "status": status,
        "telegram_message_id": msg_id,
        "error": err,
        "created_at": now,
        "sent_at": now if status == "sent" else None,
        "date_key": date_key,
    }
    post_col.insert_one(doc)
    if status == "sent":
        update = {"last_engagement_post_at": now, "updated_at": now}
        if source == "revive":
            update["last_revive_post_at"] = now
        activity_col.update_one({"chat_id": chat_id}, {"$set": update}, upsert=True)


def record_chat_activity(*, chat_id: int, message_at: datetime) -> None:
    now = _utcnow()
    get_db()["community_chat_activity"].update_one(
        {"chat_id": chat_id},
        {"$set": {"last_message_at": message_at, "updated_at": now}},
        upsert=True,
    )


def _supports_jitter(job_queue) -> bool:
    try:
        return "jitter" in signature(job_queue.run_repeating).parameters
    except Exception:
        return False


def register_engagement_jobs(application) -> None:
    settings = get_settings()
    ensure_engagement_indexes()
    jitter_supported = _supports_jitter(application.job_queue)
    common_kwargs = {"interval": timedelta(minutes=15)}
    if jitter_supported:
        common_kwargs["jitter"] = int(settings.engagement_scheduler_jitter_seconds)

    if not application.job_queue.get_jobs_by_name("engagement_posts_tick"):
        application.job_queue.run_repeating(run_engagement_posts_tick, first=20, name="engagement_posts_tick", **common_kwargs)
    if not application.job_queue.get_jobs_by_name("engagement_inactivity_revive_tick"):
        application.job_queue.run_repeating(
            run_engagement_inactivity_revive_tick,
            first=40,
            name="engagement_inactivity_revive_tick",
            **common_kwargs,
        )
