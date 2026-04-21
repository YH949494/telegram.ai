import logging
from datetime import datetime
from typing import Any, Dict, Optional

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
