"""
Default responses and reactions for each category.

Modify these dictionaries to change the wording or emojis used when the bot
interacts with users.  The key is the category returned by the classifier.
"""

import random

RESPONSES = {
    "new_user": {
        "text": (
            "Welcome to the group! 🎉\n\n"
            "<b>Voucher drops may show up anytime.</b>\n\n"
            "Turn on notifications for @advantplayofficial so you don’t miss the next one! 🔔"
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
    "deposit_question": (
        "It looks like you have a question about deposits or payment methods. "
        "An admin will assist you shortly."
    ),
    "withdrawal_question": (
        "Thanks for reaching out about your withdrawal. "
        "Our team will look into it and get back to you as soon as possible."
    ),
    "bonus_inquiry": (
        "Thanks for your interest in our promotions and bonuses! "
        "An admin will share the latest details with you shortly."
    ),
    "game_question": (
        "Looks like you have a question about our games. "
        "Our team will help answer that for you shortly."
    ),
    "loss_share": "Hang in there — better luck next time! 💪",
    "unknown": "",
}

# Reactions are sent as a lightweight response to acknowledge low‑risk messages.
# They should be simple emoji strings.  Only categories in this mapping will trigger
# a reaction.
REACTIONS = {
    # probability: chance (0.0–1.0) the bot will react at all
    "comeback_campaign": {"emojis": ["🔥", "🎉", "💪", "⚡", "🙌", "👏", "🥳", "💥"], "probability": 0.25},
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

    When the reaction config is a dict with ``emojis`` and ``probability``, the
    function returns an empty string (no reaction) with probability
    ``1 - probability``, otherwise a randomly chosen emoji from the list.

    :param category: Category returned by the classifier.
    """
    reaction = REACTIONS.get(category, "")
    if isinstance(reaction, dict):
        if random.random() > reaction["probability"]:
            return ""
        return random.choice(reaction["emojis"])
    if isinstance(reaction, list):
        return random.choice(reaction)
    return reaction
