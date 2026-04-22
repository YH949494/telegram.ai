from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from .ai_decision import DecisionResult
from .seed_rotation import SeedItem


ReplyMode = Literal["none", "deterministic", "seed", "rewrite"]


SEED_REPLIES: Dict[str, List[SeedItem]] = {
    "new_user": [
        SeedItem(key="new_user_1", text="Welcome in 👋 Glad to have you here.", tone="warm", reply_goal="welcome", allowed_contexts=("group",)),
        SeedItem(key="new_user_2", text="Hey, welcome to the community. Check the pinned info when you can.", tone="warm", reply_goal="welcome", allowed_contexts=("group",)),
        SeedItem(key="new_user_3", text="Nice to have you here. Stay tuned for updates in channel.", tone="warm", reply_goal="welcome", allowed_contexts=("group",)),
    ],
    "win_share": [
        SeedItem(key="win_share_1", text="Nice hit, congrats 🔥", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",)),
        SeedItem(key="win_share_2", text="Big win energy, congrats 🎉", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",)),
        SeedItem(key="win_share_3", text="Great result, well played.", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",)),
    ],
    "support_issue": [
        SeedItem(key="support_1", text="Thanks for reporting this. We will look into this and come back to you asap.", tone="helpful", reply_goal="clarify", allowed_contexts=("group",)),
        SeedItem(key="support_2", text="Got it. Let us look into this right now", tone="helpful", reply_goal="clarify", allowed_contexts=("group",)),
        SeedItem(key="support_3", text="Understood — let us review and come back to you at soonest", tone="helpful", reply_goal="clarify", allowed_contexts=("group",)),
    ],
    "voucher_question": [
        SeedItem(key="voucher_1", text="Please share with us your concern so we can assist.", tone="helpful", reply_goal="clarify", allowed_contexts=("group",)),
        SeedItem(key="voucher_2", text="Got it. What's the error you facing?", tone="helpful", reply_goal="clarify", allowed_contexts=("group",)),
    ],
    "positive_signal": [
        SeedItem(key="positive_1", text="Thanks for sharing that 🙌", tone="upbeat", reply_goal="encourage", allowed_contexts=("group",)),
        SeedItem(key="positive_2", text="Appreciate the kind words.", tone="upbeat", reply_goal="encourage", allowed_contexts=("group",)),
    ],
}


class ReplyPolicyResult(BaseModel):
    mode: ReplyMode
    should_send: bool
    reason: str
    category: str
    selected_seed: Optional[SeedItem] = None
    seed_candidates: List[SeedItem] = []
    use_button: bool = False
    use_parse_mode_html: bool = False
    add_reaction: bool = False
    downgrade_applied: bool = False


class ReplyPolicyService:
    def __init__(
        self,
        confidence_threshold: float,
        generation_allowed_categories: List[str],
        seed_only_categories: List[str],
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.generation_allowed_categories = set(generation_allowed_categories)
        self.seed_only_categories = set(seed_only_categories)

    def evaluate(self, decision: DecisionResult) -> ReplyPolicyResult:
        if not decision.should_reply:
            return ReplyPolicyResult(mode="none", should_send=False, reason="model_no_reply", category=decision.category)
        if decision.confidence < self.confidence_threshold:
            return ReplyPolicyResult(mode="none", should_send=False, reason="low_confidence", category=decision.category)
        if decision.safety_risk != "low":
            return ReplyPolicyResult(mode="none", should_send=False, reason="safety_risk", category=decision.category)
        if decision.category in {"ignore", "unknown"} or decision.is_low_value_noise:
            return ReplyPolicyResult(mode="none", should_send=False, reason="ignored_category", category=decision.category)
        seeds = SEED_REPLIES.get(decision.category, [])
        if not seeds:
            return ReplyPolicyResult(mode="none", should_send=False, reason="unseeded_category", category=decision.category)
        mode: ReplyMode = "seed"
        if decision.category in self.generation_allowed_categories:
            mode = "rewrite"
        if decision.category in self.seed_only_categories:
            mode = "seed"
        return ReplyPolicyResult(
            mode=mode,
            should_send=True,
            reason="allow",
            category=decision.category,
            seed_candidates=seeds[:3],
            use_button=False,
            use_parse_mode_html=False,
            add_reaction=decision.category == "win_share",
        )


def pick_deterministic_reply_seed(category: str) -> Optional[str]:
    seeds = SEED_REPLIES.get(category, [])
    return seeds[0].text if seeds else None
