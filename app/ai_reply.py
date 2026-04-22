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
            "Rewrite this reply with slight variation. Keep meaning identical. Do not add new info. "
            "Output plain text only, max 2 short lines. "
            "Do not invent rewards, policies, facts, or outcomes. Do not mention being an AI. "
            "Keep close to the seed and avoid high deviation."
        )
        reply = self.client.generate_reply(
            model=self.model,
            instructions=instructions,
            input_text=payload.json(),
        )
        return reply[:max_chars].strip()
