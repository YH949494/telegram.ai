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
    "new_user": [
        r"\bnew\b",
        r"just\s+joined",
        r"新来",
        r"新人",
        r"新来的",
        r"\bhi\b.*\bim\b.*\bnew\b",
    ],
    "voucher_question": [
        r"\bvoucher\b",
        r"promo\s*code",
        r"优惠码",
        r"红包",
    ],
    "win_share": [
        r"\bwin\b",
        r"\bwon\b",
        r"中奖了",
        r"获奖",
        r"晒.*(赢|中奖)",
    ],
    "negative_sentiment": [
        r"\bdisappoint",
        r"\bbad\b",
        r"\blost\b",
        r"\bscam\b",
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
        r"\bgreat\b",
        r"\blove\b",
        r"awesome",
        r"太棒了",
        r"开心",
    ],
}


def classify(text: str) -> str:
    """
    Classify a message into one of the defined categories.

    :param text: The message text.
    :return: The name of the category, or 'unknown' if none match.
    """
    text_lower = (text or "").lower()
    for category, patterns in CATEGORIES.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, flags=re.IGNORECASE):
                return category
    return "unknown"
