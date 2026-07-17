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
    thai_language_delete_enabled: bool = Field(True, env="THAI_LANGUAGE_DELETE_ENABLED")

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
        default_factory=lambda: [
            "support_issue", "voucher_question", "voucher_subscription",
            "deposit_question", "withdrawal_question", "bonus_inquiry", "game_question",
        ],
        env="AI_SEED_ONLY_CATEGORIES",
    )
    ai_priority_categories: List[str] = Field(
        default_factory=lambda: [
            "new_user", "support_issue", "voucher_question", "voucher_subscription",
            "win_share", "deposit_question", "withdrawal_question",
        ],
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


    engagement_posts_enabled: bool = Field(False, env="ENGAGEMENT_POSTS_ENABLED")
    engagement_posts_dry_run: bool = Field(True, env="ENGAGEMENT_POSTS_DRY_RUN")
    engagement_target_chat_ids_raw: str = Field("", env="ENGAGEMENT_TARGET_CHAT_IDS")
    engagement_timezone: str = Field("Asia/Kuala_Lumpur", env="ENGAGEMENT_TIMEZONE")
    engagement_daily_max_posts: int = Field(4, env="ENGAGEMENT_DAILY_MAX_POSTS")
    engagement_min_gap_minutes: int = Field(120, env="ENGAGEMENT_MIN_GAP_MINUTES")
    engagement_inactivity_revive_enabled: bool = Field(False, env="ENGAGEMENT_INACTIVITY_REVIVE_ENABLED")
    engagement_inactivity_minutes: int = Field(120, env="ENGAGEMENT_INACTIVITY_MINUTES")
    engagement_revive_cooldown_minutes: int = Field(360, env="ENGAGEMENT_REVIVE_COOLDOWN_MINUTES")
    engagement_native_polls_enabled: bool = Field(True, env="ENGAGEMENT_NATIVE_POLLS_ENABLED")
    engagement_default_disable_notification: bool = Field(False, env="ENGAGEMENT_DEFAULT_DISABLE_NOTIFICATION")
    engagement_quiet_hours_enabled: bool = Field(True, env="ENGAGEMENT_QUIET_HOURS_ENABLED")
    engagement_quiet_start_hour: int = Field(2, env="ENGAGEMENT_QUIET_START_HOUR")
    engagement_quiet_end_hour: int = Field(8, env="ENGAGEMENT_QUIET_END_HOUR")
    engagement_revive_daily_max_posts: int = Field(1, env="ENGAGEMENT_REVIVE_DAILY_MAX_POSTS")
    engagement_scheduler_jitter_seconds: int = Field(300, env="ENGAGEMENT_SCHEDULER_JITTER_SECONDS")
    community_helper_enabled: bool = Field(False, env="COMMUNITY_HELPER_ENABLED")
    community_helper_log_only: bool = Field(True, env="COMMUNITY_HELPER_LOG_ONLY")
    community_faq_reply_enabled: bool = Field(False, env="COMMUNITY_FAQ_REPLY_ENABLED")
    community_reactions_enabled: bool = Field(False, env="COMMUNITY_REACTIONS_ENABLED")
    community_admin_alerts_enabled: bool = Field(False, env="COMMUNITY_ADMIN_ALERTS_ENABLED")
    community_live_allowed_intents_raw: str = Field(
        "voucher_where_to_enter,voucher_code_incorrect,voucher_not_working",
        env="COMMUNITY_LIVE_ALLOWED_INTENTS",
    )
    community_reply_user_cooldown_sec: int = Field(300, env="COMMUNITY_REPLY_USER_COOLDOWN_SEC")
    community_reply_fingerprint_cooldown_sec: int = Field(600, env="COMMUNITY_REPLY_FINGERPRINT_COOLDOWN_SEC")
    community_reply_chat_cap_10m: int = Field(5, env="COMMUNITY_REPLY_CHAT_CAP_10M")
    community_reply_min_gap_minutes: int = Field(60, env="COMMUNITY_REPLY_MIN_GAP_MINUTES")
    community_reply_daily_cap: int = Field(10, env="COMMUNITY_REPLY_DAILY_CAP")
    community_reply_probability: float = Field(0.2, env="COMMUNITY_REPLY_PROBABILITY")

    welcome_image_path: str = Field("assets/ap_welcome.jpg", env="WELCOME_IMAGE_PATH")
    welcome_target_chat_id: Optional[int] = Field(None, env="WELCOME_TARGET_CHAT_ID")
    official_channel_cta_enabled: bool = Field(False, env="OFFICIAL_CHANNEL_CTA_ENABLED")
    anti_inline_spam_enabled: bool = Field(False, env="ANTI_INLINE_SPAM_ENABLED")
    anti_inline_spam_dry_run: bool = Field(True, env="ANTI_INLINE_SPAM_DRY_RUN")
    anti_inline_spam_delete: bool = Field(True, env="ANTI_INLINE_SPAM_DELETE")
    anti_inline_spam_ban: bool = Field(True, env="ANTI_INLINE_SPAM_BAN")
    anti_inline_spam_group_ids_raw: str = Field("", env="ANTI_INLINE_SPAM_GROUP_IDS")
    anti_inline_spam_allowed_user_ids_raw: str = Field("", env="ANTI_INLINE_SPAM_ALLOWED_USER_IDS")
    anti_inline_spam_allowed_usernames_raw: str = Field("", env="ANTI_INLINE_SPAM_ALLOWED_USERNAMES")
    anti_inline_spam_allowed_bot_usernames_raw: str = Field("Rose,Combot", env="ANTI_INLINE_SPAM_ALLOWED_BOT_USERNAMES")
    anti_inline_spam_allowed_domains_raw: str = Field("t.me,telegram.me", env="ANTI_INLINE_SPAM_ALLOWED_DOMAINS")
    anti_inline_spam_admin_alert_chat_id: Optional[int] = Field(None, env="ANTI_INLINE_SPAM_ADMIN_ALERT_CHAT_ID")

    auto_reply_categories: Set[str] = Field(
        default_factory=lambda: {"comeback_campaign", "new_user", "win_share", "loss_share", "positive_signal", "voucher_subscription"}
    )
    suggestion_only_categories: Set[str] = Field(
        default_factory=lambda: {
            "voucher_question",
            "support_issue",
            "negative_sentiment",
            "high_intent",
            "deposit_question",
            "withdrawal_question",
            "bonus_inquiry",
            "game_question",
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
        "community_reply_min_gap_minutes",
        "community_reply_daily_cap",
    )
    def cooldown_must_be_non_negative(cls, value: int, field):
        if value < 0:
            raise ValueError(f"{field.name} must be >= 0")
        return value





    @property
    def engagement_target_chat_ids(self) -> List[int]:
        out: List[int] = []
        for part in (self.engagement_target_chat_ids_raw or "").split(","):
            part = part.strip()
            if not part:
                continue
            out.append(int(part))
        return out

    @property
    def community_live_allowed_intents(self) -> Set[str]:
        return {
            intent.strip()
            for intent in (self.community_live_allowed_intents_raw or "").split(",")
            if intent.strip()
        }

    @staticmethod
    def _parse_int_set(raw: str) -> Set[int]:
        out: Set[int] = set()
        for part in (raw or "").split(","):
            part = part.strip()
            if not part:
                continue
            out.add(int(part))
        return out

    @staticmethod
    def _parse_lower_set(raw: str, *, strip_at: bool = False) -> Set[str]:
        out: Set[str] = set()
        for part in (raw or "").split(","):
            part = part.strip().lower()
            if strip_at:
                part = part.lstrip("@")
            if part:
                out.add(part)
        return out

    @property
    def anti_inline_spam_group_ids(self) -> Set[int]:
        return self._parse_int_set(self.anti_inline_spam_group_ids_raw)

    @property
    def anti_inline_spam_allowed_user_ids(self) -> Set[int]:
        return self._parse_int_set(self.anti_inline_spam_allowed_user_ids_raw)

    @property
    def anti_inline_spam_allowed_usernames(self) -> Set[str]:
        return self._parse_lower_set(self.anti_inline_spam_allowed_usernames_raw, strip_at=True)

    @property
    def anti_inline_spam_allowed_bot_usernames(self) -> Set[str]:
        return self._parse_lower_set(self.anti_inline_spam_allowed_bot_usernames_raw, strip_at=True)

    @property
    def anti_inline_spam_allowed_domains(self) -> Set[str]:
        return self._parse_lower_set(self.anti_inline_spam_allowed_domains_raw)

    @validator("community_reply_probability")
    def community_reply_probability_in_range(cls, value: float):
        if value < 0.0 or value > 1.0:
            raise ValueError("community_reply_probability must be between 0 and 1")
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
