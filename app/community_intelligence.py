import hashlib
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field


Action = Literal["ignore", "react_only", "reply", "admin_alert", "reply_and_admin_alert"]

DUPLICATE_REPLY_SUPPRESS_WINDOW_SEC = 600
DUPLICATE_SPIKE_THRESHOLD = 5
DUPLICATE_SPIKE_WINDOW_SEC = 600
DUPLICATE_ADMIN_ALERT_COOLDOWN_SEC = 3600
# Duplicate-policy foundation for live handler wiring:
# - first message fingerprint may receive a normal FAQ reply.
# - repeated same fingerprint inside DUPLICATE_REPLY_SUPPRESS_WINDOW_SEC should not reply again.
# - if repeated count reaches DUPLICATE_SPIKE_THRESHOLD inside DUPLICATE_SPIKE_WINDOW_SEC, emit one admin alert.
# - avoid repeated copycat replies for identical fingerprint content.
# TODO: integrate fingerprint-window checks in Telegram handler before sending replies.

_GUIDE_URL = "https://t.me/advantplayofficial/714"


class CommunityButton(BaseModel):
    text: str
    url: str


class CommunityDecision(BaseModel):
    category: str
    intent: Optional[str]
    action: Action
    reply: Optional[str]
    emoji: Optional[str]
    buttons: list[CommunityButton] = Field(default_factory=list)
    admin_alert: bool
    sensitive: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    fingerprint: Optional[str]


FAQ_RULES = {
    "voucher_where_to_enter": {
        "category": "voucher",
        "reply": "Copy the voucher code and follow the guide below.",
        "emoji": "👀",
        "buttons": [CommunityButton(text="View Guide", url=_GUIDE_URL)],
    },
    "voucher_code_incorrect": {
        "category": "voucher",
        "reply": "The code may be expired, already used, entered incorrectly, or fully claimed. Please check with platform Customer Service for further help.",
        "emoji": "👀",
        "buttons": [CommunityButton(text="View Guide", url=_GUIDE_URL)],
    },
    "voucher_not_working": {
        "category": "voucher",
        "reply": "The code may be expired, already used, entered incorrectly, or fully claimed. Please check with platform Customer Service for further help.",
        "emoji": "👀",
        "buttons": [CommunityButton(text="View Guide", url=_GUIDE_URL)],
    },
    "free_spin_claim_how": {
        "category": "free_spin",
        "reply": "Please follow the Free Spin guide below.",
        "buttons": [CommunityButton(text="View Guide", url=_GUIDE_URL)],
    },
    "free_spin_redeem_in_game": {
        "category": "free_spin",
        "reply": "Please follow the Free Spin guide below.",
        "buttons": [CommunityButton(text="View Guide", url=_GUIDE_URL)],
    },
    "free_spin_video_guide": {
        "category": "free_spin",
        "reply": "Please follow the Free Spin guide below.",
        "buttons": [CommunityButton(text="View Guide", url=_GUIDE_URL)],
    },
    "new_user_start": {
        "category": "account",
        "reply": "Welcome! Follow the official channel first, then open the Mini App to check available rewards.",
        "buttons": [CommunityButton(text="Official Channel", url="https://t.me/advantplayofficial")],
    },
    "miniapp_access_how": {
        "category": "account",
        "reply": "Tap the Mini App button below to check and redeem available rewards.",
        "buttons": [CommunityButton(text="Open Mini App", url="https://t.me/APreferralV1_bot?start=start")],
    },
    "mywin_submit_how": {
        "category": "mywin",
        "reply": "Submit your win in the community group and follow the campaign rules.",
        "buttons": [CommunityButton(text="Join Community Group", url="https://t.me/+tgGbOPvp1p05NjA9")],
    },
    "mywin_hashtags": {
        "category": "mywin",
        "reply": "Use #MyWin for normal wins. If it is over 50x, use #ComebackIsReal too.",
        "buttons": [],
    },
    "mywin_comeback_tag": {
        "category": "mywin",
        "reply": "If your win is over 50x, include #ComebackIsReal with #MyWin.",
        "buttons": [],
    },
    "official_channel_follow_how": {
        "category": "channel",
        "reply": "Follow the official channel to get announcements and voucher drops.",
        "buttons": [CommunityButton(text="Official Channel", url="https://t.me/advantplayofficial")],
    },
    "voucher_claim_how": {"category": "voucher", "reply": "Claim vouchers from official drops and redeem them in the Mini App.", "emoji": "👀"},
    "voucher_expired_or_fully_claimed": {"category": "voucher", "reply": "That voucher may be expired or fully claimed.", "emoji": "👀"},
    "voucher_claim_limit": {"category": "voucher", "reply": "Voucher claims are limited per campaign rules.", "emoji": "👀"},
    "voucher_next_drop": {"category": "voucher", "reply": "Follow the official channel for the next voucher drop time.", "emoji": "👀"},
    "voucher_drop_notification": {"category": "voucher", "reply": "Turn on channel notifications so you do not miss voucher drops.", "emoji": "👀"},
    "free_spin_terms": {"category": "free_spin", "reply": "Free Spin eligibility and limits follow current campaign terms."},
    "campaign_available": {"category": "campaign", "reply": "Campaign availability depends on current announcements and your eligibility."},
    "daily_checkin_how": {"category": "campaign", "reply": "Use the Mini App daily check-in feature to claim check-in rewards when available."},
    "campaign_rewards_join_how": {"category": "campaign", "reply": "Join active campaigns from official posts and complete the listed tasks."},
    "silver_bonus_available": {"category": "campaign", "reply": "Silver bonus availability follows current campaign announcements."},
    "notification_turn_on_how": {"category": "channel", "reply": "Open the official channel and enable notifications from Telegram settings."},
    "chatroom_vs_channel": {"category": "channel", "reply": "Channel posts official updates; group chat is for community discussion."},
}

SENSITIVE_PATTERNS = [
    ("customer_service_contact", ["customer service", "support", "helpdesk", "cs contact"]),
    ("warned_or_removed", ["warned", "removed", "kicked", "banned", "muted"]),
    ("referral_links_allowed", ["referral link", "affiliate link", "post link", "share link"]),
    ("transaction_history_check", ["transaction history", "bet history", "history check"]),
    ("deposit", ["deposit", "top up", "topup"]),
    ("withdrawal", ["withdraw", "cash out", "cashout"]),
    ("account_issue", ["account issue", "cannot login", "cant login", "login failed"]),
    ("account_locked", ["account locked", "locked account", "freeze account"]),
    ("kyc", ["kyc", "verification", "verify account"]),
    ("payment_dispute", ["payment dispute", "payment failed", "money not received"]),
    ("bonus_dispute", ["bonus dispute", "bonus missing", "bonus not credited"]),
]

FAQ_PATTERNS = [
    ("voucher_where_to_enter", ["where enter voucher", "where to enter voucher", "enter code where"]),
    ("voucher_code_incorrect", ["code incorrect", "invalid code", "wrong code"]),
    ("voucher_not_working", ["code not working", "voucher not working", "promo not working"]),
    ("free_spin_claim_how", ["how claim free spin", "claim free spin"]),
    ("free_spin_redeem_in_game", ["redeem free spin", "use free spin", "free spin in game"]),
    ("free_spin_video_guide", ["free spin video", "spin guide", "tutorial free spin"]),
    ("new_user_start", ["new here", "just joined", "how to start", "new user"]),
    ("miniapp_access_how", ["mini app", "open miniapp", "access mini app"]),
    ("mywin_submit_how", ["submit mywin", "post my win", "share mywin"]),
    ("mywin_hashtags", ["hashtags", "tag for mywin", "mywin hashtag"]),
    ("mywin_comeback_tag", ["over 50x", ">50x", "50x", "comebackisreal"]),
    ("official_channel_follow_how", ["official channel", "follow channel"]),
    ("voucher_claim_how", ["claim voucher", "get voucher"]),
    ("voucher_expired_or_fully_claimed", ["voucher expired", "fully claimed"]),
    ("voucher_claim_limit", ["voucher limit", "claim limit"]),
    ("voucher_next_drop", ["next voucher drop", "next drop"]),
    ("voucher_drop_notification", ["voucher notification", "drop notification"]),
    ("free_spin_terms", ["free spin terms", "free spin rule"]),
    ("campaign_available", ["campaign available", "what campaign"]),
    ("daily_checkin_how", ["daily check in", "daily checkin"]),
    ("campaign_rewards_join_how", ["join campaign", "campaign rewards"]),
    ("silver_bonus_available", ["silver bonus"]),
    ("notification_turn_on_how", ["turn on notification", "enable notification"]),
    ("chatroom_vs_channel", ["channel vs group", "chatroom vs channel"]),
]


def normalize_for_fingerprint(text: str | None) -> str:
    if not text:
        return ""
    value = text.lower().strip()
    value = re.sub(r"https?://\S+|www\.\S+", " ", value)
    value = re.sub(r"@\w+", " ", value)
    value = re.sub(r"([\W_])\1+", r"\1", value)
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not re.search(r"[a-z0-9]", value):
        return ""
    return value


def message_fingerprint(text: str | None) -> str | None:
    normalized = normalize_for_fingerprint(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _match_intent(normalized: str, patterns: list[tuple[str, list[str]]]) -> Optional[str]:
    for intent, keys in patterns:
        if any(k in normalized for k in keys):
            return intent
    return None


def classify_community_message(
    text: str | None,
    *,
    has_photo: bool = False,
    has_video: bool = False,
    user_id: int | None = None,
    username: str | None = None,
) -> CommunityDecision:
    del user_id, username
    normalized = normalize_for_fingerprint(text)
    fingerprint = message_fingerprint(text)

    if not normalized:
        return CommunityDecision(
            category="unknown",
            intent=None,
            action="ignore",
            reply=None,
            emoji=None,
            buttons=[],
            admin_alert=False,
            sensitive=False,
            confidence=0.2,
            reason="empty_or_non_informative",
            fingerprint=fingerprint,
        )

    sensitive_intent = _match_intent(normalized, SENSITIVE_PATTERNS)
    if sensitive_intent:
        return CommunityDecision(
            category="sensitive",
            intent=sensitive_intent,
            action="admin_alert",
            reply=None,
            emoji="🙏" if "support" in normalized or "help" in normalized else None,
            buttons=[],
            admin_alert=True,
            sensitive=True,
            confidence=0.86,
            reason="sensitive_topic_no_public_reply",
            fingerprint=fingerprint,
        )

    # legacy intents intentionally disabled for normal FAQ auto-replies
    if "activation left" in normalized or "account register" in normalized:
        return CommunityDecision(
            category="disabled_intent",
            intent=None,
            action="ignore",
            reply=None,
            emoji=None,
            buttons=[],
            admin_alert=False,
            sensitive=False,
            confidence=0.8,
            reason="disabled_legacy_faq_intent",
            fingerprint=fingerprint,
        )

    intent = _match_intent(normalized, FAQ_PATTERNS)
    if intent:
        rule = FAQ_RULES[intent]
        emoji = rule.get("emoji")
        if (has_photo or has_video) and intent.startswith("mywin"):
            emoji = "🔥"
        return CommunityDecision(
            category=rule["category"],
            intent=intent,
            action="reply",
            reply=rule["reply"],
            emoji=emoji,
            buttons=rule.get("buttons", []),
            admin_alert=False,
            sensitive=False,
            confidence=0.88,
            reason="faq_match",
            fingerprint=fingerprint,
        )

    return CommunityDecision(
        category="unknown",
        intent=None,
        action="ignore",
        reply=None,
        emoji=None,
        buttons=[],
        admin_alert=False,
        sensitive=False,
        confidence=0.35,
        reason="no_rule_matched",
        fingerprint=fingerprint,
    )
