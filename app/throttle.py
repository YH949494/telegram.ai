import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Literal, Tuple

from .config import Settings

logger = logging.getLogger(__name__)

ThrottleReason = Literal["none", "category_cooldown", "user_cooldown", "duplicate_text"]


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    reason: ThrottleReason
    normalized_text: str = ""
    normalized_text_hash: str = ""


class AutoReplyThrottle:
    def __init__(self) -> None:
        self._category_last_reply: Dict[Tuple[int, str], float] = {}
        self._user_last_reply: Dict[Tuple[int, int], float] = {}
        self._text_last_reply: Dict[Tuple[int, str], float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def normalize_text(text: str) -> str:
        normalized = (text or "").lower().strip()
        normalized = normalized.replace("’", "'")
        normalized = normalized.replace("'", "")
        normalized = re.sub(r"[^\w\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _hash_text(normalized_text: str) -> str:
        return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _category_cooldown_seconds(category: str, settings: Settings) -> int:
        category_cooldowns = {
            "new_user": settings.auto_reply_new_user_cooldown_seconds,
            "positive_signal": settings.auto_reply_positive_signal_cooldown_seconds,
            "win_share": settings.auto_reply_win_share_cooldown_seconds,
        }
        return category_cooldowns.get(category, settings.auto_reply_default_category_cooldown_seconds)

    def evaluate_auto_reply_throttle(
        self,
        chat_id: int,
        user_id: int,
        category: str,
        text: str,
        settings: Settings,
    ) -> ThrottleDecision:
        if not settings.enable_auto_reply_throttle:
            return ThrottleDecision(allowed=True, reason="none")

        now = time.time()
        normalized_text = self.normalize_text(text)
        normalized_text_hash = self._hash_text(normalized_text) if normalized_text else ""

        with self._lock:
            category_key = (chat_id, category)
            category_last = self._category_last_reply.get(category_key)
            category_cooldown = self._category_cooldown_seconds(category, settings)
            if category_last is not None and now - category_last < category_cooldown:
                return ThrottleDecision(
                    allowed=False,
                    reason="category_cooldown",
                    normalized_text=normalized_text,
                    normalized_text_hash=normalized_text_hash,
                )

            user_key = (chat_id, user_id)
            user_last = self._user_last_reply.get(user_key)
            if user_last is not None and now - user_last < settings.auto_reply_user_cooldown_seconds:
                return ThrottleDecision(
                    allowed=False,
                    reason="user_cooldown",
                    normalized_text=normalized_text,
                    normalized_text_hash=normalized_text_hash,
                )

            text_key = (chat_id, normalized_text_hash)
            text_last = self._text_last_reply.get(text_key) if normalized_text_hash else None
            if (
                text_last is not None
                and normalized_text_hash
                and now - text_last < settings.auto_reply_duplicate_window_seconds
            ):
                return ThrottleDecision(
                    allowed=False,
                    reason="duplicate_text",
                    normalized_text=normalized_text,
                    normalized_text_hash=normalized_text_hash,
                )

            self._category_last_reply[category_key] = now
            self._user_last_reply[user_key] = now
            if normalized_text_hash:
                self._text_last_reply[text_key] = now

        logger.info(
            "Auto-reply throttle allowed chat_id=%s user_id=%s category=%s normalized_hash=%s",
            chat_id,
            user_id,
            category,
            normalized_text_hash,
        )
        return ThrottleDecision(
            allowed=True,
            reason="none",
            normalized_text=normalized_text,
            normalized_text_hash=normalized_text_hash,
        )


auto_reply_throttle = AutoReplyThrottle()
