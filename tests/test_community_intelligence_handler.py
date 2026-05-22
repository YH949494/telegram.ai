import types
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app import handlers


class DummyUser:
    def __init__(self, user_id=123, is_bot=False, username="user"):
        self.id = user_id
        self.is_bot = is_bot
        self.username = username


class DummyMessage:
    def __init__(self, text=None, caption=None, user=None, photo=None, video=None):
        self.text = text
        self.caption = caption
        self.chat_id = 999
        self.message_id = 1001
        self.from_user = user or DummyUser()
        self.reply_text = AsyncMock()
        self.date = datetime.utcnow()
        self.photo = photo
        self.video = video


class CommunityIntelligenceHandlerTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self, **kwargs):
        base = dict(
            community_helper_enabled=False,
            community_helper_log_only=True,
            community_faq_reply_enabled=False,
            community_reactions_enabled=False,
            community_admin_alerts_enabled=False,
            enable_tagging=False,
            enable_suggestions=False,
            enable_low_risk_auto_reply=False,
            enable_threaded_replies=True,
            enable_auto_reply_throttle=True,
            enable_ai_decision=False,
            openai_api_key=None,
        )
        base.update(kwargs)
        return types.SimpleNamespace(**base)

    async def test_helper_disabled_does_not_classify_or_store(self):
        update = types.SimpleNamespace(message=DummyMessage(text="where to enter voucher code"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42))
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message") as ci_classify, \
             patch("app.handlers.log_community_intelligence_event") as ci_log:
            await handlers.message_handler(update, context)
        ci_classify.assert_not_called()
        ci_log.assert_not_called()

    async def test_helper_enabled_log_only_classifies_and_persists(self):
        update = types.SimpleNamespace(message=DummyMessage(caption="my win over 50x", photo=[1]))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42))
        ci_decision = types.SimpleNamespace(
            fingerprint="abc",
            category="mywin",
            intent="mywin_comeback_tag",
            action="reply",
            confidence=0.88,
            sensitive=False,
            admin_alert=False,
            emoji="🔥",
            reason="faq_match",
        )
        with patch("app.handlers.get_settings", return_value=self._settings(community_helper_enabled=True)), \
             patch("app.handlers.classify_community_message", return_value=ci_decision) as ci_classify, \
             patch("app.handlers.log_community_intelligence_event") as ci_log:
            await handlers.message_handler(update, context)

        ci_classify.assert_called_once()
        ci_log.assert_called_once()
        doc = ci_log.call_args.args[0]
        self.assertEqual(doc["intent"], "mywin_comeback_tag")
        self.assertTrue(doc["has_photo"])
        self.assertFalse(doc["has_video"])
        self.assertTrue(doc["would_reply"])
        self.assertTrue(doc["would_react"])
        self.assertFalse(doc["would_alert_admin"])

    async def test_text_sample_truncated_to_200(self):
        long_text = "x" * 350
        update = types.SimpleNamespace(message=DummyMessage(text=long_text))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42))
        ci_decision = types.SimpleNamespace(
            fingerprint="abc",
            category="unknown",
            intent=None,
            action="ignore",
            confidence=0.2,
            sensitive=False,
            admin_alert=False,
            emoji=None,
            reason="empty_or_non_informative",
        )
        with patch("app.handlers.get_settings", return_value=self._settings(community_helper_enabled=True)), \
             patch("app.handlers.classify_community_message", return_value=ci_decision), \
             patch("app.handlers.log_community_intelligence_event") as ci_log:
            await handlers.message_handler(update, context)
        doc = ci_log.call_args.args[0]
        self.assertEqual(len(doc["text_sample"]), 200)

    async def test_db_write_failure_does_not_raise(self):
        update = types.SimpleNamespace(message=DummyMessage(text="where to enter voucher"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42))
        ci_decision = types.SimpleNamespace(
            fingerprint="abc", category="voucher", intent="voucher_where_to_enter", action="reply", confidence=0.9,
            sensitive=False, admin_alert=False, emoji="👀", reason="faq_match",
        )
        with patch("app.handlers.get_settings", return_value=self._settings(community_helper_enabled=True)), \
             patch("app.handlers.classify_community_message", return_value=ci_decision), \
             patch("app.handlers.log_community_intelligence_event", side_effect=RuntimeError("db down")):
            await handlers.message_handler(update, context)

    async def test_unknown_does_not_create_noisy_flags(self):
        update = types.SimpleNamespace(message=DummyMessage(text="???"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42))
        ci_decision = types.SimpleNamespace(
            fingerprint=None,
            category="unknown",
            intent=None,
            action="ignore",
            confidence=0.35,
            sensitive=False,
            admin_alert=False,
            emoji=None,
            reason="no_rule_matched",
        )
        with patch("app.handlers.get_settings", return_value=self._settings(community_helper_enabled=True)), \
             patch("app.handlers.classify_community_message", return_value=ci_decision), \
             patch("app.handlers.log_community_intelligence_event") as ci_log:
            await handlers.message_handler(update, context)
        doc = ci_log.call_args.args[0]
        self.assertFalse(doc["would_reply"])
        self.assertFalse(doc["would_react"])
        self.assertFalse(doc["would_alert_admin"])


if __name__ == "__main__":
    unittest.main()
