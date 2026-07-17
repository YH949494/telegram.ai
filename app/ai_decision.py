import logging
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, validator

from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)

Category = Literal[
    "new_user",
    "voucher_question",
    "support_issue",
    "win_share",
    "loss_share",
    "deposit_question",
    "withdrawal_question",
    "bonus_inquiry",
    "game_question",
    "game_recommendation",
    "positive_signal",
    "negative_sentiment",
    "affiliate_interest",
    "high_intent",
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
                "loss_share",
                "deposit_question",
                "withdrawal_question",
                "bonus_inquiry",
                "game_question",
                "game_recommendation",
                "positive_signal",
                "negative_sentiment",
                "affiliate_interest",
                "high_intent",
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


DECISION_INSTRUCTIONS_BASE = (
    "You are classifying messages in a Telegram community group for AdvantPlay, an online gaming platform. "
    "Members use this group to: share wins/losses, ask about vouchers/promo codes, report technical issues, "
    "ask about deposits/withdrawals/bonuses/games, express sentiment, and engage with the community. "
    "The group is multilingual — members write in English and Chinese. "
    "The bot's job is to engage meaningfully without being noisy or spammy. "
    "Unnecessary replies are harmful. Prefer precision over recall and default to silence.\n\n"
    "CATEGORY RULES:\n"
    "- win_share: User sharing THEIR OWN actual game result. "
    "  YES: 'I won RM500!', 'just hit jackpot', 'cashed out today', '赢了'. "
    "  NO: 'max win is 100x', 'daily recommendation', 'this game has high rtp', '推荐'. "
    "  Key: personal first-person result, not game stats or recommendations.\n"
    "- loss_share: User sharing that they lost or had bad luck in a game. "
    "  YES: 'I lost so much today', 'bad luck streak', 'keep losing', '输了', '亏了'. "
    "  NO: complaints about the platform or accusations of scam (those are negative_sentiment).\n"
    "- new_user: User explicitly identifying themselves as new to the group. "
    "  YES: 'just joined', 'im new here', '新人', '刚加入'. "
    "  NO: messages that merely mention 'new' in another context (e.g. 'new voucher', 'new game').\n"
    "- voucher_question: User asking about or having trouble with a specific voucher/promo code.\n"
    "- deposit_question: User asking how to deposit, about payment methods, top-up options, or minimum deposit. "
    "  YES: 'how to deposit', 'what payment methods', 'how do I top up', '如何充值', '充值方式'.\n"
    "- withdrawal_question: User asking about withdrawals — how to withdraw, withdrawal status, processing time, or withdrawal failures. "
    "  YES: 'how to withdraw', 'my withdrawal is pending', 'when will I receive my money', '怎么提款', '提现失败'.\n"
    "- bonus_inquiry: User asking about bonuses, cashback, reload promotions, loyalty points, or free credits. "
    "  YES: 'is there a welcome bonus', 'how to claim cashback', 'any reload bonus', '返水', '红利'.\n"
    "- game_question: User asking about what games are available, how to play a specific game, or game recommendations. "
    "  YES: 'what games do you have', 'how to play slots', 'recommend a game', '怎么玩', '推荐游戏'.\n"
    "- support_issue: User reporting a technical problem — login failure, payment error, withdrawal stuck, account locked.\n"
    "- positive_signal: User expressing genuine appreciation or satisfaction (not just noise).\n"
    "- negative_sentiment: User expressing frustration, complaint, or accusing the platform of wrongdoing.\n"
    "- high_intent: User expressing strong interest in affiliate programs, referrals, or earning more rewards.\n"
    "- ignore: Spam, off-topic chat, bot commands, or low-value noise.\n"
    "Output only schema-compliant JSON."
)


class AIDecisionService:
    def __init__(self, client: OpenAIClient, model: str) -> None:
        self.client = client
        self.model = model

    def decide(self, text: str, few_shot_examples: Optional[List[dict]] = None) -> DecisionResult:
        instructions = DECISION_INSTRUCTIONS_BASE
        if few_shot_examples:
            example_lines = []
            for ex in few_shot_examples[:5]:
                example_lines.append(
                    f'Message: "{ex["text"]}" → category: {ex["category"]}, should_reply: {ex["should_reply"]}'
                )
            instructions = instructions + "\n\nPAST APPROVED EXAMPLES:\n" + "\n".join(example_lines)
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
