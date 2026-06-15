import types
import unittest

from app.anti_inline_spam import detect_anti_inline_spam


def make_settings(**kwargs):
    payload = {
        "anti_inline_spam_allowed_user_ids": set(),
        "anti_inline_spam_allowed_usernames": set(),
        "anti_inline_spam_allowed_bot_usernames": {"rose", "combot"},
        "anti_inline_spam_allowed_domains": {"t.me", "telegram.me"},
    }
    payload.update(kwargs)
    return types.SimpleNamespace(**payload)


def make_message(**kwargs):
    user = kwargs.pop("user", types.SimpleNamespace(id=123, username="member", is_bot=False))
    payload = {
        "from_user": user,
        "text": None,
        "caption": None,
        "reply_markup": None,
        "photo": None,
        "video": None,
        "animation": None,
        "document": None,
        "via_bot": None,
        "entities": [],
        "caption_entities": [],
    }
    payload.update(kwargs)
    return types.SimpleNamespace(**payload)


class AntiInlineSpamDetectorTests(unittest.TestCase):
    def test_username_ending_bot_matches(self):
        message = make_message(user=types.SimpleNamespace(id=1, username="PromoBot", is_bot=False))
        decision = detect_anti_inline_spam(message, make_settings(), text="")
        self.assertTrue(decision.matched)
        self.assertIn("username_endswith_bot", decision.reasons)

    def test_via_bot_matches(self):
        message = make_message(via_bot=types.SimpleNamespace(id=9))
        decision = detect_anti_inline_spam(message, make_settings(), text="")
        self.assertTrue(decision.matched)
        self.assertIn("via_bot", decision.reasons)

    def test_url_button_matches(self):
        reply_markup = types.SimpleNamespace(inline_keyboard=[[types.SimpleNamespace(url="https://spam.example")]])
        message = make_message(reply_markup=reply_markup)
        decision = detect_anti_inline_spam(message, make_settings(), text="")
        self.assertTrue(decision.matched)
        self.assertIn("url_button", decision.reasons)

    def test_media_with_reply_markup_matches(self):
        reply_markup = types.SimpleNamespace(inline_keyboard=[[types.SimpleNamespace(callback_data="x")]])
        message = make_message(photo=["photo"], reply_markup=reply_markup)
        decision = detect_anti_inline_spam(message, make_settings(), text="")
        self.assertTrue(decision.matched)
        self.assertIn("media_with_reply_markup", decision.reasons)

    def test_porn_keyword_matches(self):
        message = make_message(text="fresh leaked archive")
        decision = detect_anti_inline_spam(message, make_settings(), text=message.text)
        self.assertTrue(decision.matched)
        self.assertIn("porn_keyword", decision.reasons)

    def test_text_link_non_allowlist_matches(self):
        entity = types.SimpleNamespace(type="text_link", url="https://bad.example/path")
        message = make_message(text="click", entities=[entity])
        decision = detect_anti_inline_spam(message, make_settings(), text=message.text)
        self.assertTrue(decision.matched)
        self.assertIn("non_allowlisted_entity_url", decision.reasons)

    def test_allowlisted_username_skips(self):
        user = types.SimpleNamespace(id=1, username="trusted", is_bot=False)
        reply_markup = types.SimpleNamespace(inline_keyboard=[[types.SimpleNamespace(url="https://spam.example")]])
        message = make_message(user=user, reply_markup=reply_markup)
        decision = detect_anti_inline_spam(
            message,
            make_settings(anti_inline_spam_allowed_usernames={"trusted"}),
            text="nude",
        )
        self.assertFalse(decision.matched)

    def test_allowlisted_domain_skips_entity_url(self):
        entity = types.SimpleNamespace(type="text_link", url="https://t.me/advantplayofficial")
        message = make_message(text="official", entities=[entity])
        decision = detect_anti_inline_spam(message, make_settings(), text=message.text)
        self.assertFalse(decision.matched)


if __name__ == "__main__":
    unittest.main()
