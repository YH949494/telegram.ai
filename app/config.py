from functools import lru_cache
from typing import List, Optional, Set

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

    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    openai_decision_model: str = Field("gpt-4.1-mini", env="OPENAI_DECISION_MODEL")
    openai_generation_model: str = Field("gpt-4.1-mini", env="OPENAI_GENERATION_MODEL")
    enable_ai_decision: bool = Field(False, env="ENABLE_AI_DECISION")
    enable_ai_generation: bool = Field(False, env="ENABLE_AI_GENERATION")
    enable_ai_moderation: bool = Field(True, env="ENABLE_AI_MODERATION")
    ai_decision_confidence_threshold: float = Field(0.82, env="AI_DECISION_CONFIDENCE_THRESHOLD")
    ai_rule_threshold: float = Field(0.88, env="AI_RULE_THRESHOLD")
    ai_ambiguous_categories: List[str] = Field(
        default_factory=lambda: ["win_share", "positive_signal", "unknown"],
        env="AI_AMBIGUOUS_CATEGORIES",
    )
    ai_max_reply_chars: int = Field(220, env="AI_MAX_REPLY_CHARS")
    ai_seed_repeat_window_seconds: int = Field(300, env="AI_SEED_REPEAT_WINDOW_SECONDS")
    ai_generation_rewrite_mode: bool = Field(True, env="AI_GENERATION_REWRITE_MODE")
    ai_max_seed_reuse_per_window: int = Field(1, env="AI_MAX_SEED_REUSE_PER_WINDOW")
    enable_seed_rotation_memory: bool = Field(True, env="ENABLE_SEED_ROTATION_MEMORY")
    ai_max_decisions_per_minute: int = Field(30, env="AI_MAX_DECISIONS_PER_MINUTE")
    ai_max_generations_per_minute: int = Field(10, env="AI_MAX_GENERATIONS_PER_MINUTE")
    ai_max_decisions_per_chat_per_hour: int = Field(120, env="AI_MAX_DECISIONS_PER_CHAT_PER_HOUR")
    ai_enable_budget_downgrade: bool = Field(True, env="AI_ENABLE_BUDGET_DOWNGRADE")
    ai_generation_allowed_categories: List[str] = Field(
        default_factory=lambda: ["win_share", "new_user", "positive_signal"],
        env="AI_GENERATION_ALLOWED_CATEGORIES",
    )
    ai_seed_only_categories: List[str] = Field(
        default_factory=lambda: ["support_issue", "voucher_question", "voucher_subscription"],
        env="AI_SEED_ONLY_CATEGORIES",
    )
    ai_priority_categories: List[str] = Field(
        default_factory=lambda: ["new_user", "support_issue", "voucher_question", "voucher_subscription", "win_share"],
        env="AI_PRIORITY_CATEGORIES",
    )
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
    comeback_reaction_cooldown_seconds: int = Field(300, env="COMEBACK_REACTION_COOLDOWN_SECONDS")

    engagement_topics_enabled: bool = Field(False, env="ENGAGEMENT_TOPICS_ENABLED")
    engagement_topic_ai_enabled: bool = Field(False, env="ENGAGEMENT_TOPIC_AI_ENABLED")
    engagement_topic_chat_id: Optional[int] = Field(None, env="ENGAGEMENT_TOPIC_CHAT_ID")
    engagement_topic_min_interval_hours: int = Field(48, env="ENGAGEMENT_TOPIC_MIN_INTERVAL_HOURS")
    engagement_topic_daily_cap: int = Field(1, env="ENGAGEMENT_TOPIC_DAILY_CAP")
    engagement_topic_seed_cooldown_days: int = Field(30, env="ENGAGEMENT_TOPIC_SEED_COOLDOWN_DAYS")
    engagement_topic_text_cooldown_days: int = Field(60, env="ENGAGEMENT_TOPIC_TEXT_COOLDOWN_DAYS")
    engagement_topic_max_chars: int = Field(120, env="ENGAGEMENT_TOPIC_MAX_CHARS")
    engagement_topic_require_quiet: bool = Field(False, env="ENGAGEMENT_TOPIC_REQUIRE_QUIET")
    engagement_topic_min_quiet_minutes: int = Field(45, env="ENGAGEMENT_TOPIC_MIN_QUIET_MINUTES")
    engagement_topic_scheduler_interval_hours: int = Field(6, env="ENGAGEMENT_TOPIC_SCHEDULER_INTERVAL_HOURS")
    engagement_topic_openai_model: str = Field("gpt-4o-mini", env="ENGAGEMENT_TOPIC_OPENAI_MODEL")

    community_helper_enabled: bool = Field(False, env="COMMUNITY_HELPER_ENABLED")
    community_helper_log_only: bool = Field(True, env="COMMUNITY_HELPER_LOG_ONLY")
    community_faq_reply_enabled: bool = Field(False, env="COMMUNITY_FAQ_REPLY_ENABLED")
    community_reactions_enabled: bool = Field(False, env="COMMUNITY_REACTIONS_ENABLED")
    community_admin_alerts_enabled: bool = Field(False, env="COMMUNITY_ADMIN_ALERTS_ENABLED")

    auto_reply_categories: Set[str] = Field(
        default_factory=lambda: {"comeback_campaign", "new_user", "win_share", "positive_signal", "voucher_subscription"}
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
        "comeback_reaction_cooldown_seconds",
    )
    def cooldown_must_be_non_negative(cls, value: int, field):
        if value < 0:
            raise ValueError(f"{field.name} must be >= 0")
        return value


    @validator("ai_decision_confidence_threshold")
    def ai_threshold_in_range(cls, value: float):
        if value < 0.0 or value > 1.0:
            raise ValueError("ai_decision_confidence_threshold must be between 0 and 1")
        return value

    @validator("ai_rule_threshold")
    def ai_rule_threshold_in_range(cls, value: float):
        if value < 0.0 or value > 1.0:
            raise ValueError("ai_rule_threshold must be between 0 and 1")
        return value

    @validator("ai_max_reply_chars")
    def ai_max_reply_chars_positive(cls, value: int):
        if value <= 0:
            raise ValueError("ai_max_reply_chars must be > 0")
        return value

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
