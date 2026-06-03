import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app import handlers
from app.community_intelligence import CommunityButton


class DummyUser:
    def __init__(self, user_id=123, is_bot=False, username="user"):
        self.id = user_id
        self.is_bot = is_bot
        self.username = username


class DummyMessage:
    def __init__(self, text="voucher not working", user=None):
        self.text = text
        self.caption = None
        self.chat_id = 999
        self.message_id = 1001
        self.from_user = user or DummyUser()
        self.reply_text = AsyncMock()
        self.date = datetime.now(timezone.utc)
        self.photo = None
        self.video = None


class CommunityHelperLiveReplyTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self, **kwargs):
        base = dict(
            community_helper_enabled=True,
            community_helper_log_only=False,
            community_faq_reply_enabled=True,
            community_reactions_enabled=False,
            community_admin_alerts_enabled=False,
            community_live_allowed_intents={"voucher_where_to_enter", "voucher_code_incorrect", "voucher_not_working"},
            community_reply_user_cooldown_sec=300,
            community_reply_fingerprint_cooldown_sec=600,
            community_reply_chat_cap_10m=5,
            community_reply_min_gap_minutes=60,
            community_reply_daily_cap=10,
            community_reply_probability=1.0,
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

    def _decision(self, **kwargs):
        base = dict(
            fingerprint="fp",
            category="voucher",
            intent="voucher_not_working",
            action="reply",
            confidence=0.9,
            sensitive=False,
            admin_alert=False,
            emoji=None,
            reason="faq_match",
            reply="Try updating app and re-enter the voucher.",
            buttons=None,
        )
        base.update(kwargs)
        return types.SimpleNamespace(**base)

    async def test_log_only_does_not_send(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings(community_helper_log_only=True)), \
             patch("app.handlers.classify_community_message", return_value=self._decision()), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event"):
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_not_called()

    async def test_intent_not_allowed_does_not_send_and_persists_suppressed(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message", return_value=self._decision(intent="mywin_submit_flow")), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event") as reply_log:
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_not_called()
        self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "not_allowed_intent")

    async def test_allowed_intent_sends_reply_and_persists(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message", return_value=self._decision()), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 0, 0]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event") as reply_log:
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_called_once()
        self.assertTrue(reply_log.call_args.args[0]["reply_sent"])

    async def test_model_buttons_markup_included(self):
        update = types.SimpleNamespace(message=DummyMessage())
        decision = self._decision(
            intent="voucher_where_to_enter",
            buttons=[CommunityButton(text="Open app", url="https://example.com")],
        )
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message", return_value=decision), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 0, 0]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event"):
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        kwargs = update.message.reply_text.call_args.kwargs
        self.assertIsNotNone(kwargs.get("reply_markup"))

    async def test_dict_buttons_markup_included(self):
        update = types.SimpleNamespace(message=DummyMessage())
        decision = self._decision(
            intent="voucher_where_to_enter",
            buttons=[{"text": "Open app", "url": "https://example.com"}],
        )
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message", return_value=decision), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 0, 0]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event"):
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        kwargs = update.message.reply_text.call_args.kwargs
        self.assertIsNotNone(kwargs.get("reply_markup"))

    async def test_invalid_buttons_do_not_crash_and_send_without_markup(self):
        update = types.SimpleNamespace(message=DummyMessage())
        decision = self._decision(
            intent="voucher_where_to_enter",
            buttons=[{"text": "Open app"}, types.SimpleNamespace(text=" ", url="https://example.com"), object()],
        )
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message", return_value=decision), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 0, 0]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event"):
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        kwargs = update.message.reply_text.call_args.kwargs
        self.assertIsNone(kwargs.get("reply_markup"))

    async def test_duplicate_fingerprint_user_cooldown_chat_cap_and_db_failure_suppress(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings()), patch("app.handlers.classify_community_message", return_value=self._decision()), patch("app.handlers.log_community_intelligence_event"), patch("app.handlers.log_community_helper_reply_event") as reply_log:
            with patch("app.handlers.count_recent_community_helper_replies", side_effect=[1]):
                await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
                self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "duplicate_fingerprint")
            with patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 1]):
                await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
                self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "user_cooldown")
            with patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 5]):
                await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
                self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "chat_cap")
            with patch("app.handlers.count_recent_community_helper_replies", side_effect=RuntimeError("db")):
                await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
                self.assertEqual(reply_log.call_args.args[0]["reply_sent"], False)

    async def test_reply_blocked_by_min_gap(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message", return_value=self._decision()), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 1]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event") as reply_log, \
             self.assertLogs("app.handlers", level="INFO") as logs:
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_not_called()
        self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "min_gap")
        self.assertTrue(any("reply_skipped_min_gap" in line for line in logs.output))

    async def test_reply_blocked_by_daily_cap(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings(community_reply_daily_cap=10)), \
             patch("app.handlers.classify_community_message", return_value=self._decision()), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 0, 10]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event") as reply_log, \
             self.assertLogs("app.handlers", level="INFO") as logs:
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_not_called()
        self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "daily_cap")
        self.assertTrue(any("reply_skipped_daily_cap" in line for line in logs.output))

    async def test_reply_blocked_by_probability(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings(community_reply_probability=0.2)), \
             patch("app.handlers.classify_community_message", return_value=self._decision()), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 0, 0]), \
             patch("app.handlers.random.random", return_value=0.9), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event") as reply_log, \
             self.assertLogs("app.handlers", level="INFO") as logs:
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_not_called()
        self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "probability")
        self.assertTrue(any("reply_skipped_probability" in line for line in logs.output))

    async def test_reaction_still_happens_when_reply_throttled(self):
        update = types.SimpleNamespace(message=DummyMessage())
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock()))
        with patch("app.handlers.get_settings", return_value=self._settings(community_reactions_enabled=True)), \
             patch("app.handlers.classify_community_message", return_value=self._decision(emoji="👀")), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 1]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event"):
            await handlers.message_handler(update, context)
        self.assertEqual(context.bot.set_message_reaction.await_count, 1)
        update.message.reply_text.assert_not_called()

    async def test_high_value_reply_still_respects_throttle(self):
        update = types.SimpleNamespace(message=DummyMessage())
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.classify_community_message", return_value=self._decision(intent="voucher_where_to_enter")), \
             patch("app.handlers.count_recent_community_helper_replies", side_effect=[0, 0, 0, 1]), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event") as reply_log:
            await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_not_called()
        self.assertEqual(reply_log.call_args.args[0]["suppress_reason"], "min_gap")

    async def test_disabled_helper_sends_nothing(self):
        update = types.SimpleNamespace(message=DummyMessage())
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock()))
        with patch("app.handlers.get_settings", return_value=self._settings(community_helper_enabled=False)), \
             patch("app.handlers.classify_community_message") as ci_classify, \
             patch("app.handlers.classify_message") as classify:
            await handlers.message_handler(update, context)
        ci_classify.assert_not_called()
        classify.assert_not_called()
        context.bot.set_message_reaction.assert_not_called()
        update.message.reply_text.assert_not_called()

    async def test_sensitive_admin_alert_and_blocked_intents_never_send(self):
        update = types.SimpleNamespace(message=DummyMessage())
        cases = [
            self._decision(sensitive=True),
            self._decision(admin_alert=True),
            self._decision(intent="mywin_claim"),
            self._decision(intent="new_user_start"),
            self._decision(intent="free_spin_join"),
        ]
        with patch("app.handlers.get_settings", return_value=self._settings()), \
             patch("app.handlers.log_community_intelligence_event"), \
             patch("app.handlers.log_community_helper_reply_event"):
            for case in cases:
                with patch("app.handlers.classify_community_message", return_value=case):
                    await handlers.message_handler(update, types.SimpleNamespace(bot=types.SimpleNamespace(id=42)))
        update.message.reply_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
