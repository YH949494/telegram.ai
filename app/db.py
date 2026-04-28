import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None


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
            "date": message.date or datetime.utcnow(),
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
            "date": datetime.utcnow(),
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
        update: Dict[str, Any] = {"approved": approved, "feedback_date": datetime.utcnow()}
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
