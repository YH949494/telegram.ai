from datetime import datetime
from typing import Optional

from pymongo import MongoClient

from .config import get_settings

"""
Database utilities for logging messages.

This module uses PyMongo to insert documents into a MongoDB collection.  All
database operations are synchronous for simplicity.  In a high‑traffic scenario
consider using an async MongoDB client (e.g. Motor) or running DB operations in
a separate thread.
"""

_client: Optional[MongoClient] = None


def get_db():
    """
    Return a MongoDB database instance.  Lazily initialises the client on first use.
    """
    global _client
    settings = get_settings()
    if _client is None:
        _client = MongoClient(settings.mongodb_uri)
    return _client[settings.mongodb_db]


def log_message(category: str, update) -> None:
    """
    Persist a message and its classification to the database.

    :param category: Category assigned to the message.
    :param update: Telegram Update object containing the message.
    """
    try:
        db = get_db()
        settings = get_settings()
        collection = db[settings.mongodb_collection]
        message = update.message
        doc = {
            "message_id": message.message_id,
            "chat_id": message.chat_id,
            "user_id": message.from_user.id if message.from_user else None,
            "username": message.from_user.username if message.from_user else None,
            "text": message.text,
            "category": category,
            "date": message.date or datetime.utcnow(),
        }
        collection.insert_one(doc)
    except Exception as exc:
        # In the event of a DB error, print to stderr.  Logging to a proper logger
        # would be preferable in a production system.
        print(f"Database log failed: {exc}")
