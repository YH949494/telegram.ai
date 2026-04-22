import logging
from typing import Literal

from pydantic import BaseModel, Field, validator

from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)

Category = Literal[
    "new_user",
    "voucher_question",
    "support_issue",
    "win_share",
    "game_recommendation",
    "positive_signal",
    "negative_sentiment",
    "affiliate_interest",
    "general_question",
    "ignore",
    "unknown",
]
Tone = Literal["warm", "upbeat", "concise", "helpful", "celebratory", "neutral"]
ReplyGoal = Literal["welcome", "answer_question", "celebrate", "encourage", "redirect", "clarify", "do_not_reply"]
SafetyRisk = Literal["low", "medium", "high"]
ReplyStyle = Literal["short_direct", "friendly_short", "celebratory_short", "helpful_short", "no_reply"]


class DecisionResult(BaseModel):
    should_reply: bool
    category: Category
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    tone: Tone
    reply_goal: ReplyGoal
    safety_risk: SafetyRisk
    suggested_reply_style: ReplyStyle
    user_intent_summary: str
    mentions_game_result: bool
    mentions_recommendation: bool
    mentions_support_issue: bool
    mentions_new_user_signal: bool
    is_low_value_noise: bool

    @validator("reason", "user_intent_summary", pre=True)
    def _default_str(cls, value: str) -> str:
        return (value or "").strip()


DECISION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "should_reply": {"type": "boolean"},
        "category": {
            "type": "string",
            "enum": [
                "new_user",
                "voucher_question",
                "support_issue",
                "win_share",
                "game_recommendation",
                "positive_signal",
                "negative_sentiment",
                "affiliate_interest",
                "general_question",
                "ignore",
                "unknown",
            ],
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "tone": {"type": "string", "enum": ["warm", "upbeat", "concise", "helpful", "celebratory", "neutral"]},
        "reply_goal": {
            "type": "string",
            "enum": ["welcome", "answer_question", "celebrate", "encourage", "redirect", "clarify", "do_not_reply"],
        },
        "safety_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "suggested_reply_style": {
            "type": "string",
            "enum": ["short_direct", "friendly_short", "celebratory_short", "helpful_short", "no_reply"],
        },
        "user_intent_summary": {"type": "string"},
        "mentions_game_result": {"type": "boolean"},
        "mentions_recommendation": {"type": "boolean"},
        "mentions_support_issue": {"type": "boolean"},
        "mentions_new_user_signal": {"type": "boolean"},
        "is_low_value_noise": {"type": "boolean"},
    },
    "required": [
        "should_reply",
        "category",
        "confidence",
        "reason",
        "tone",
        "reply_goal",
        "safety_risk",
        "suggested_reply_style",
        "user_intent_summary",
        "mentions_game_result",
        "mentions_recommendation",
        "mentions_support_issue",
        "mentions_new_user_signal",
        "is_low_value_noise",
    ],
}


class AIDecisionService:
    def __init__(self, client: OpenAIClient, model: str) -> None:
        self.client = client
        self.model = model

    def decide(self, text: str) -> DecisionResult:
        instructions = (
            "You are classifying whether a Telegram community bot should reply in a public group chat. "
            "Unnecessary replies are harmful. Prefer precision over recall and default to silence. "
            "Distinguish win-share from recommendations: phrases like 'max win', 'daily recommendation', "
            "'recommended game', or 'this game has 100000x max win' are not win-share by default. "
            "Output only schema-compliant JSON."
        )
        data = self.client.decision_response(
            model=self.model,
            input_text=text,
            json_schema=DECISION_JSON_SCHEMA,
            instructions=instructions,
        )
        result = DecisionResult.parse_obj(data)
        logger.info(
            "AI decision category=%s confidence=%.2f should_reply=%s",
            result.category,
            result.confidence,
            result.should_reply,
        )
        return result
