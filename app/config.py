from functools import lru_cache
from typing import Set, Optional

from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables or `.env` files.

    Sensitive values such as tokens and database URIs should be provided via
    environment variables or Fly.io secrets rather than checked into source control.
    """

    telegram_token: str = Field(..., env="TELEGRAM_TOKEN")
    mongodb_uri: str = Field(..., env="MONGODB_URI")
    mongodb_db: str = Field("telegram_ai", env="MONGODB_DB")
    mongodb_collection: str = Field("messages", env="MONGODB_COLLECTION")
    admin_chat_id: Optional[int] = Field(None, env="ADMIN_CHAT_ID")
    # Categories for which the bot should reply automatically.  All other categories
    # will only generate suggestions for a human admin.
    auto_reply_categories: Set[str] = {"new_user", "win_share", "positive_signal"}
    suggestion_only_categories: Set[str] = {
        "voucher_question",
        "support_issue",
        "negative_sentiment",
        "high_intent",
    }

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Return a cached Settings instance.  Pydantic will read environment variables and
    assign defaults where appropriate.
    """
    return Settings()
