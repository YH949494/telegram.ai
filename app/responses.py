"""
Default responses and reactions for each category.

Modify these dictionaries to change the wording or emojis used when the bot
interacts with users.  The key is the category returned by the classifier.
"""

RESPONSES = {
    "new_user": {
        "text": (
            "Welcome to the group! 🎉\n\n"
            "<b>Surprise voucher drops can happen anytime.</b>\n\n"
            "Make sure you turn on notifications for @advantplayofficial so you don’t miss the next one! 💵"
        ),
        "button_text": "Join Official Channel",
        "button_url": "https://t.me/advantplayofficial"
    },
    "win_share": "Congratulations on your win! 🥳",
    "positive_signal": "Thank you for your feedback! 😊",
    "voucher_question": (
        "It looks like you have a question about vouchers or promo codes. "
        "An admin will assist you shortly."
    ),
    "support_issue": (
        "Thanks for reporting the issue. One of our admins will look into it and get back to you soon."
    ),
    "negative_sentiment": (
        "We're sorry to hear that you're not satisfied. An admin will reach out to help resolve the issue."
    ),
    "high_intent": (
        "Great to see your enthusiasm! Our team will provide more information about "
        "rewards and affiliate opportunities soon."
    ),
    "voucher_subscription": {
        "text": (
            "New vouchers drop regularly. Stay subscribed to @advantplayofficial so you don't miss the next one! 💵"
        ),
        "button_text": "Join Official Channel",
        "button_url": "https://t.me/advantplayofficial"
    },
    "unknown": "",
}

# Reactions are sent as a lightweight response to acknowledge low‑risk messages.
# They should be simple emoji strings.  Only categories in this mapping will trigger
# a reaction.
REACTIONS = {
    "new_user": "👋",
    "win_share": "🎉",
    "positive_signal": "❤️",
}


def generate_reply(category: str, text: str) -> str:
    """
    Return an appropriate reply for a given category.  If no reply is defined
    for the category, an empty string is returned.

    :param category: Category returned by the classifier.
    :param text: Original message text (unused but included for future flexibility).
    """
    return RESPONSES.get(category, "")


def get_reaction(category: str) -> str:
    """
    Return the emoji reaction for a given category, or an empty string if none is defined.

    :param category: Category returned by the classifier.
    """
    return REACTIONS.get(category, "")
