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
        instructions = (
            "Rewrite this seed reply with natural variation in wording and sentence structure. "
            "Keep the same intent — do not add new facts, rewards, policies, or outcomes. "
            "You may lightly reflect the user's message context to feel more personal, but do not invent details. "
            "Output plain text only, max 2 short lines. Do not mention being an AI. "
            "The reply should feel fresh and human, not a near-copy of the seed."
        )
        reply = self.client.generate_reply(
            model=self.model,
            instructions=instructions,
            input_text=payload.json(),
        )
        return reply[:max_chars].strip()
