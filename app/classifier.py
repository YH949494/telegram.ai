import re
from typing import Dict, List

"""
Rule‑based classifier for incoming messages.

This module defines a mapping from categories to regular expression patterns.
Each incoming message is matched against these patterns in order; the first
match determines the category.  If no patterns match, the category 'unknown'
is returned.

This is intentionally simple.  For production use you may wish to replace
or augment this with a trained model or external API call.
"""

# Patterns grouped by category.  Add or refine patterns here to customise
# classification.  Patterns are evaluated case‑insensitively.
CATEGORIES: Dict[str, List[str]] = {
    "voucher_subscription": [
        r"vouchers?\s+drop",
        r"drop\s+regular",
        r"stay\s+subscri",
        r"subscribe\s+to\s+\w*channel",
        r"subscrib\w+\s+to\s+\w*channel",
        r"channel\s+to\s+get\s+voucher",
    ],
    "new_user": [
        r"\bi'?m\s+new\s+here\b",
        r"\bi\s+am\s+new\s+here\b",
        r"\bi'?m\s+new\s+(?:to\s+(?:this|the)\s+group|member)\b",
        r"\bjust\s+joined\b",
        r"\bnew\s+(?:here|member|to\s+(?:this|the)\s+group)\b",
        r"\bhi\b.{0,30}\bnew\b.{0,30}\bhere\b",
        r"\bhello\b.{0,20}\bnew\b.{0,20}\bhere\b",
        r"新人",
        r"新来的?",
        r"刚加入",
    ],
    "voucher_question": [
        r"\bvoucher\b",
        r"promo\s*code",
        r"优惠码",
        r"红包",
    ],
    "win_share": [
        r"\bwon\s+\d+(?:\.\d+)?(?:x)?\b",
        r"中奖了",
        r"获奖",
        r"晒.*(赢|中奖)",
    ],
    "negative_sentiment": [
        r"\bdisappoint",
        r"\bscam\b",
        r"\bnot\s+working\b",
        r"\bstill\s+(?:waiting|no\s+reply)\b",
        r"不满意",
        r"差劲",
        r"不好",
    ],
    "high_intent": [
        r"how\s+to\s+get\s+more\s+reward",
        r"more\s+reward",
        r"affiliate",
        r"更多奖励",
        r"邀请.*奖励",
    ],
    "support_issue": [
        r"\berror\b",
        r"\bissue\b",
        r"\bproblem\b",
        r"\bcannot\b",
        r"\bcan't\b",
        r"无法",
        r"失败",
        r"bug",
    ],
    "positive_signal": [
        r"\bthank\s+you\b",
        r"\bthanks\b",
        r"\bgreat\s+(?:job|service|support|team|work|platform|game)\b",
        r"\blove\s+(?:this|it|the)\b",
        r"awesome",
        r"太棒了",
        r"开心",
    ],
}

WIN_SHARE_NEGATIVE_PATTERNS: List[str] = [
    r"daily\s+recommendation",
    r"\brecommend(?:ed|ation)?\b",
    r"recommend\s+only",
    r"max\s+win",
    r"med\s*max",
    r"this\s+game\s+has",
]

WIN_SHARE_POSITIVE_PATTERNS: List[str] = [
    r"\bi\s+won\b",
    r"\bmy\s+win\b",
    r"\bi\s+got\b",
    r"\bi\s+hit\b",
    r"\bcash\s*out\b",
    r"\bcashed\s*out\b",
    r"\bwon\s+\d+(?:\.\d+)?(?:x)?\b",
    r"\bwon\s+(?:big|huge|jackpot)\b",
    r"\bwithdrew\b",
    r"\bwithdrawn\b",
    r"晒.*(赢|中奖)",
    r"中奖了",
    r"获奖",
]

WIN_SHARE_WEAK_POSITIVE_PATTERNS: List[str] = [
    r"\b\d+(?:\.\d+)?x\s+win\b",
    r"\b(?:big|nice)\s+win\b",
    r"\bfinally\s+hit\s+bonus\b",
    r"\bjackpot\b",
    r"\bfull\s*screen\b",
    r"\bcash\s*out\b",
    r"\bcashed\s*out\b",
]

def is_win_share(text: str) -> bool:
    if any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in WIN_SHARE_NEGATIVE_PATTERNS
    ):
        return False
    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in WIN_SHARE_POSITIVE_PATTERNS
    ) or any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in WIN_SHARE_WEAK_POSITIVE_PATTERNS
    )


def classify(text: str) -> str:
    """
    Classify a message into one of the defined categories.

    :param text: The message text.
    :return: The name of the category, or 'unknown' if none match.
    """
    text_lower = (text or "").lower()
    for category, patterns in CATEGORIES.items():
        if category == "win_share":
            if is_win_share(text_lower):
                return category
            continue
        for pattern in patterns:
            if re.search(pattern, text_lower, flags=re.IGNORECASE):
                return category
    return "unknown"
