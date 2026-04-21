from functools import lru_cache
from typing import Optional, Set

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    telegram_token: str = Field(..., env="TELEGRAM_TOKEN")
    mongodb_uri: str = Field(..., env="MONGODB_URI")
    mongodb_db: str = Field("telegram_ai", env="MONGODB_DB")
    mongodb_collection: str = Field("messages", env="MONGODB_COLLECTION")
    admin_chat_id: Optional[int] = Field(None, env="ADMIN_CHAT_ID")
    port: int = Field(8000, env="PORT")

    enable_tagging: bool = Field(True, env="ENABLE_TAGGING")
    enable_suggestions: bool = Field(True, env="ENABLE_SUGGESTIONS")
    enable_low_risk_auto_reply: bool = Field(True, env="ENABLE_LOW_RISK_AUTO_REPLY")
    enable_threaded_replies: bool = Field(True, env="ENABLE_THREADED_REPLIES")
    enable_auto_reply_throttle: bool = Field(True, env="ENABLE_AUTO_REPLY_THROTTLE")
    auto_reply_new_user_cooldown_seconds: int = Field(120, env="AUTO_REPLY_NEW_USER_COOLDOWN_SECONDS")
    auto_reply_positive_signal_cooldown_seconds: int = Field(
        45, env="AUTO_REPLY_POSITIVE_SIGNAL_COOLDOWN_SECONDS"
    )
    auto_reply_win_share_cooldown_seconds: int = Field(30, env="AUTO_REPLY_WIN_SHARE_COOLDOWN_SECONDS")
    auto_reply_default_category_cooldown_seconds: int = Field(
        60, env="AUTO_REPLY_DEFAULT_CATEGORY_COOLDOWN_SECONDS"
    )
    auto_reply_user_cooldown_seconds: int = Field(120, env="AUTO_REPLY_USER_COOLDOWN_SECONDS")
    auto_reply_duplicate_window_seconds: int = Field(180, env="AUTO_REPLY_DUPLICATE_WINDOW_SECONDS")

    auto_reply_categories: Set[str] = Field(
        default_factory=lambda: {"new_user", "win_share", "positive_signal"}
    )
    suggestion_only_categories: Set[str] = Field(
        default_factory=lambda: {
            "voucher_question",
            "support_issue",
            "negative_sentiment",
            "high_intent",
        }
    )

    @validator("telegram_token", "mongodb_uri")
    def must_not_be_blank(cls, value: str, field):
        if not value or not value.strip():
            raise ValueError(f"{field.name} is required and cannot be empty")
        return value

    @validator(
        "auto_reply_new_user_cooldown_seconds",
        "auto_reply_positive_signal_cooldown_seconds",
        "auto_reply_win_share_cooldown_seconds",
        "auto_reply_default_category_cooldown_seconds",
        "auto_reply_user_cooldown_seconds",
        "auto_reply_duplicate_window_seconds",
    )
    def cooldown_must_be_non_negative(cls, value: int, field):
        if value < 0:
            raise ValueError(f"{field.name} must be >= 0")
        return value

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
