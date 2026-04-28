from pydantic import BaseModel

from .ai_decision import DecisionResult
from .openai_client import OpenAIClient


class ReplyGenerationInput(BaseModel):
    category: str
    tone: str
    reply_goal: str
    style: str
    user_text: str
    seed_text: str
    max_chars: int


class AIReplyService:
    def __init__(self, client: OpenAIClient, model: str) -> None:
        self.client = client
        self.model = model

    def generate(self, decision: DecisionResult, user_text: str, seed_text: str, max_chars: int) -> str:
        payload = ReplyGenerationInput(
            category=decision.category,
            tone=decision.tone,
            reply_goal=decision.reply_goal,
            style=decision.suggested_reply_style,
            user_text=user_text,
            seed_text=seed_text,
            max_chars=max_chars,
        )
        category_hints = {
            "new_user": "Welcome them warmly. Mention that voucher drops happen in the community and they should turn on notifications.",
            "win_share": "Celebrate their win briefly and authentically. Keep it short — 1 line max. Do not invent win amounts or game names.",
            "positive_signal": "Acknowledge their appreciation naturally. Keep it brief and genuine.",
            "support_issue": "Acknowledge the issue and assure them the team will look into it. Do not promise specific timelines.",
            "voucher_question": "Ask them to share more details so you can help.",
        }
        hint = category_hints.get(decision.category, "")
        instructions = (
            "You write replies for an AdvantPlay gaming community Telegram group. "
            "Rewrite the seed reply with natural variation — different words and sentence structure. "
            "Rules:\n"
            "- Do not add new facts, rewards, amounts, game names, or policies not in the seed.\n"
            "- Do not mention being an AI or a bot.\n"
            "- Max 2 short lines. Plain text only (no markdown).\n"
            "- Sound human and conversational, not corporate.\n"
            f"- Category hint: {hint}\n" if hint else
            "- Category hint: match the intent of the seed.\n"
            "Output only the reply text."
        )
        reply = self.client.generate_reply(
            model=self.model,
            instructions=instructions,
            input_text=payload.json(),
        )
        return reply[:max_chars].strip()
