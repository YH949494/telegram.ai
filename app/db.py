import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .config import get_settings
from .time_utils import normalize_utc_datetime, utc_now

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_community_indexes_ready: bool = False
_community_reply_indexes_ready: bool = False


def get_db():
    global _client
    settings = get_settings()
    if _client is None:
        _client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
        logger.info("MongoDB client initialized")
    return _client[settings.mongodb_db]


def log_message(
    category: str,
    update,
    decision: Optional[Dict[str, Any]] = None,
    throttle_blocked: bool = False,
    throttle_reason: str = "none",
) -> None:
    try:
        db = get_db()
        settings = get_settings()
        collection = db[settings.mongodb_collection]
        message = update.message
        if message is None:
            return
        doc = {
            "message_id": message.message_id,
            "chat_id": message.chat_id,
            "user_id": message.from_user.id if message.from_user else None,
            "username": message.from_user.username if message.from_user else None,
            "text": message.text,
            "category": category,
            "decision": decision or {},
            "throttle_blocked": throttle_blocked,
            "throttle_reason": throttle_reason,
            "date": normalize_utc_datetime(getattr(message, "date", None)),
        }
        collection.insert_one(doc)
        logger.info("Mongo log inserted message_id=%s", message.message_id)
    except PyMongoError:
        logger.exception("Mongo logging failed due to database error")
    except Exception:
        logger.exception("Mongo logging failed due to unexpected error")


def log_suggestion(
    *,
    bot_message_id: int,
    original_message_id: int,
    chat_id: int,
    original_text: str,
    suggested_reply: str,
    category: str,
) -> None:
    """Store a forwarded suggestion so admin feedback can be linked back to it."""
    try:
        db = get_db()
        settings = get_settings()
        db["suggestions"].insert_one({
            "bot_message_id": bot_message_id,
            "original_message_id": original_message_id,
            "chat_id": chat_id,
            "original_text": original_text,
            "suggested_reply": suggested_reply,
            "category": category,
            "approved": None,
            "correct_category": None,
            "date": utc_now(),
        })
    except Exception:
        logger.exception("Failed to log suggestion bot_message_id=%s", bot_message_id)


def log_feedback(
    *,
    bot_message_id: int,
    approved: bool,
    correct_category: Optional[str] = None,
) -> bool:
    """Record admin feedback (approve/reject) for a forwarded suggestion. Returns True if found."""
    try:
        db = get_db()
        settings = get_settings()
        col = db["suggestions"]
        update: Dict[str, Any] = {"approved": approved, "feedback_date": utc_now()}
        if correct_category:
            update["correct_category"] = correct_category
        result = col.update_one({"bot_message_id": bot_message_id}, {"$set": update})
        return result.matched_count > 0
    except Exception:
        logger.exception("Failed to log feedback for bot_message_id=%s", bot_message_id)
        return False


def get_few_shot_examples(category: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return recently approved examples for a category to use as few-shot prompts."""
    try:
        db = get_db()
        settings = get_settings()
        col = db["suggestions"]
        docs = list(
            col.find(
                {"approved": True, "$or": [{"category": category}, {"correct_category": category}]},
                {"original_text": 1, "suggested_reply": 1, "category": 1, "correct_category": 1},
                sort=[("feedback_date", -1)],
            ).limit(limit)
        )
        results = []
        for d in docs:
            results.append({
                "text": d.get("original_text", ""),
                "category": d.get("correct_category") or d.get("category"),
                "should_reply": True,
                "reply": d.get("suggested_reply", ""),
            })
        return results
    except Exception:
        logger.exception("Failed to fetch few-shot examples for category=%s", category)
        return []


def _ensure_community_intelligence_indexes(db) -> None:
    global _community_indexes_ready
    if _community_indexes_ready:
        return
    try:
        col = db["community_intelligence_events"]
        col.create_index([("created_at", -1)], background=True)
        col.create_index([("chat_id", 1), ("created_at", -1)], background=True)
        col.create_index([("fingerprint", 1), ("chat_id", 1), ("created_at", -1)], background=True)
        col.create_index([("intent", 1), ("created_at", -1)], background=True)
        col.create_index([("sensitive", 1), ("created_at", -1)], background=True)
        _community_indexes_ready = True
    except Exception:
        logger.warning("Community intelligence index setup failed", exc_info=True)


def _ensure_community_reply_event_indexes(db) -> None:
    global _community_reply_indexes_ready
    if _community_reply_indexes_ready:
        return
    try:
        col = db["community_helper_reply_events"]
        col.create_index([("created_at", -1)], background=True)
        col.create_index([("chat_id", 1), ("created_at", -1)], background=True)
        col.create_index([("chat_id", 1), ("fingerprint", 1), ("created_at", -1)], background=True)
        col.create_index([("user_id", 1), ("created_at", -1)], background=True)
        _community_reply_indexes_ready = True
    except Exception:
        logger.warning("Community helper reply index setup failed", exc_info=True)


def log_community_intelligence_event(doc: Dict[str, Any]) -> None:
    try:
        db = get_db()
        _ensure_community_intelligence_indexes(db)
        db["community_intelligence_events"].insert_one(doc)
    except Exception:
        logger.warning("Failed to persist community intelligence event", exc_info=True)


def log_community_helper_reply_event(doc: Dict[str, Any]) -> None:
    db = get_db()
    _ensure_community_reply_event_indexes(db)
    db["community_helper_reply_events"].insert_one(doc)


def count_recent_community_helper_replies(*, since: datetime, chat_id: Optional[int] = None, user_id: Optional[int] = None, fingerprint: Optional[str] = None) -> int:
    db = get_db()
    _ensure_community_reply_event_indexes(db)
    query: Dict[str, Any] = {"created_at": {"$gte": since}, "reply_sent": True}
    if chat_id is not None:
        query["chat_id"] = chat_id
    if user_id is not None:
        query["user_id"] = user_id
    if fingerprint:
        query["fingerprint"] = fingerprint
    return db["community_helper_reply_events"].count_documents(query, limit=1 if fingerprint or user_id else 0)


def aggregate_community_helper_events(*, since: datetime, limit: int = 10, sample_limit: int = 5) -> Dict[str, Any]:
    db = get_db()
    col = db["community_intelligence_events"]
    match = {"created_at": {"$gte": since}}

    totals = list(
        col.aggregate(
            [
                {"$match": match},
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": 1},
                        "would_reply": {"$sum": {"$cond": ["$would_reply", 1, 0]}},
                        "would_react": {"$sum": {"$cond": ["$would_react", 1, 0]}},
                        "would_alert_admin": {"$sum": {"$cond": ["$would_alert_admin", 1, 0]}},
                        "sensitive": {"$sum": {"$cond": ["$sensitive", 1, 0]}},
                        "unknown": {"$sum": {"$cond": [{"$eq": ["$category", "unknown"]}, 1, 0]}},
                    }
                },
            ]
        )
    )
    base = totals[0] if totals else {"total": 0, "would_reply": 0, "would_react": 0, "would_alert_admin": 0, "sensitive": 0, "unknown": 0}

    def _top(field: str) -> List[Dict[str, Any]]:
        return list(
            col.aggregate(
                [
                    {"$match": match},
                    {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": limit},
                ]
            )
        )

    duplicates = list(
        col.aggregate(
            [
                {"$match": {**match, "fingerprint": {"$ne": None}}},
                {"$sort": {"created_at": -1}},
                {
                    "$group": {
                        "_id": "$fingerprint",
                        "count": {"$sum": 1},
                        "sample_text": {"$first": "$text_sample"},
                        "intent": {"$first": "$intent"},
                        "category": {"$first": "$category"},
                    }
                },
                {"$match": {"count": {"$gte": 2}}},
                {"$sort": {"count": -1}},
                {"$limit": limit},
            ]
        )
    )

    def _samples(filter_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list(
            col.find(
                {**match, **filter_doc},
                {"intent": 1, "category": 1, "text_sample": 1, "_id": 0},
                sort=[("created_at", -1)],
                limit=sample_limit,
            )
        )

    return {
        **base,
        "unknown_rate": (base["unknown"] / base["total"] * 100.0) if base["total"] else 0.0,
        "top_intents": _top("intent"),
        "top_categories": _top("category"),
        "top_duplicates": duplicates,
        "sensitive_samples": _samples({"sensitive": True}),
        "unknown_samples": _samples({"category": "unknown"}),
    }
