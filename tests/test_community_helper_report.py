import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.handlers import (
    parse_report_window,
    build_community_helper_report,
    community_helper_report_handler,
)


class DummyMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.reply_text = AsyncMock()


class ReportTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_windows(self):
        self.assertEqual(parse_report_window("6h")[1], "Last 6h")
        self.assertEqual(parse_report_window("24h")[1], "Last 24h")
        self.assertEqual(parse_report_window("7d")[1], "Last 7d")
        self.assertEqual(parse_report_window("oops")[1], "Last 24h")

    def test_report_includes_totals_and_rate(self):
        stats = {
            "total": 100,
            "would_reply": 20,
            "would_react": 10,
            "would_alert_admin": 5,
            "sensitive": 7,
            "unknown": 40,
            "unknown_rate": 40.0,
            "top_intents": [{"_id": "voucher_not_working", "count": 14}],
            "top_categories": [{"_id": "voucher", "count": 25}],
            "top_duplicates": [{"sample_text": "x" * 100, "count": 4, "intent": "voucher_not_working", "category": "voucher"}],
            "sensitive_samples": [{"intent": "withdrawal", "text_sample": "withdraw not received"}],
            "unknown_samples": [{"text_sample": "??"}],
        }
        text = build_community_helper_report("Last 24h", stats)
        self.assertIn("Total classified: 100", text)
        self.assertIn("Would reply: 20", text)
        self.assertIn("Sensitive: 7", text)
        self.assertIn("Unknown rate: 40.0%", text)
        self.assertIn("...", text)

    def test_report_empty(self):
        text = build_community_helper_report("Last 24h", {"total": 0})
        self.assertIn("No telemetry found", text)

    async def test_command_admin_only(self):
        msg = DummyMessage(chat_id=2)
        update = types.SimpleNamespace(message=msg)
        context = types.SimpleNamespace(args=[])
        settings = types.SimpleNamespace(admin_chat_id=1)
        with patch("app.handlers.get_settings", return_value=settings):
            await community_helper_report_handler(update, context)
        msg.reply_text.assert_awaited_once()
        self.assertIn("admin-only", msg.reply_text.await_args.args[0])

    async def test_command_handles_mongo_failure(self):
        msg = DummyMessage(chat_id=1)
        update = types.SimpleNamespace(message=msg)
        context = types.SimpleNamespace(args=[])
        settings = types.SimpleNamespace(admin_chat_id=1)
        with patch("app.handlers.get_settings", return_value=settings), \
             patch("app.handlers.aggregate_community_helper_events", side_effect=RuntimeError("db")):
            await community_helper_report_handler(update, context)
        self.assertIn("Could not generate", msg.reply_text.await_args.args[0])

    async def test_report_since_uses_timezone_aware_utc(self):
        msg = DummyMessage(chat_id=1)
        update = types.SimpleNamespace(message=msg)
        context = types.SimpleNamespace(args=["24h"])
        settings = types.SimpleNamespace(admin_chat_id=1)
        fixed_now = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

        def _assert_since(*, since):
            self.assertIsNotNone(since.tzinfo)
            self.assertEqual(since.tzinfo, timezone.utc)
            self.assertEqual(since, fixed_now - timedelta(hours=24))
            return {"total": 0}

        with patch("app.handlers.get_settings", return_value=settings),              patch("app.handlers.utc_now", return_value=fixed_now),              patch("app.handlers.aggregate_community_helper_events", side_effect=_assert_since):
            await community_helper_report_handler(update, context)


if __name__ == "__main__":
    unittest.main()
