import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app import engagement_topics


class EngagementTopicTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self, **kwargs):
        base = dict(
            engagement_topics_enabled=True,
            engagement_topic_ai_enabled=False,
            engagement_topic_chat_id=999,
            engagement_topic_min_interval_hours=48,
            engagement_topic_daily_cap=1,
            engagement_topic_seed_cooldown_days=30,
            engagement_topic_text_cooldown_days=60,
            engagement_topic_max_chars=120,
            engagement_topic_require_quiet=False,
            engagement_topic_scheduler_interval_hours=6,
            engagement_topic_openai_model="gpt-4o-mini",
            openai_api_key=None,
            openai_generation_model="gpt-4.1-mini",
        )
        base.update(kwargs)
        return types.SimpleNamespace(**base)

    async def test_disabled_flag_skips(self):
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        with patch("app.engagement_topics.get_settings", return_value=self._settings(engagement_topics_enabled=False)):
            await engagement_topics.run_engagement_topic_job(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_missing_chat_id_skips(self):
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        col = types.SimpleNamespace(find_one=lambda *a, **k: None, count_documents=lambda *a, **k: 0)
        with patch("app.engagement_topics._history_col", return_value=(col, self._settings(engagement_topic_chat_id=None))):
            await engagement_topics.run_engagement_topic_job(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_interval_gate_skips(self):
        now = datetime.now(timezone.utc)
        col = types.SimpleNamespace(
            find_one=lambda *a, **k: {"sent_at": now - timedelta(hours=1)},
            count_documents=lambda *a, **k: 0,
        )
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        with patch("app.engagement_topics._history_col", return_value=(col, self._settings())), patch("app.engagement_topics._utcnow", return_value=now):
            await engagement_topics.run_engagement_topic_job(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_daily_cap_gate_skips(self):
        now = datetime.now(timezone.utc)
        col = types.SimpleNamespace(
            find_one=lambda *a, **k: None,
            count_documents=lambda *a, **k: 1,
        )
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        with patch("app.engagement_topics._history_col", return_value=(col, self._settings())), patch("app.engagement_topics._utcnow", return_value=now):
            await engagement_topics.run_engagement_topic_job(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    def test_blocked_ai_output_rejected(self):
        cleaned, reason = engagement_topics._sanitize_question("Should I deposit now?", 120, True)
        self.assertIsNone(cleaned)
        self.assertIn("blocked_phrase", reason)

    def test_hard_words_rejected(self):
        cleaned, reason = engagement_topics._sanitize_question("bankroll discipline volatility strategy?", 120, True)
        self.assertIsNone(cleaned)
        self.assertTrue(reason.startswith("hard_word:"))

    def test_more_than_18_words_rejected(self):
        text = "a b c d e f g h i j k l m n o p q r s?"
        cleaned, reason = engagement_topics._sanitize_question(text, 120, True)
        self.assertIsNone(cleaned)
        self.assertEqual(reason, "too_many_words")

    def test_simple_question_passes(self):
        cleaned, reason = engagement_topics._sanitize_question("Fast spin or normal spin — which one you like?", 120, True)
        self.assertEqual(cleaned, "Fast spin or normal spin — which one you like?")
        self.assertIsNone(reason)

    def test_bare_www_url_rejected(self):
        cleaned, reason = engagement_topics._sanitize_question("Check this www.example.com?", 120, True)
        self.assertIsNone(cleaned)
        self.assertEqual(reason, "contains_url")

    def test_uppercase_www_url_rejected(self):
        cleaned, reason = engagement_topics._sanitize_question("Check this WWW.example.com?", 120, True)
        self.assertIsNone(cleaned)
        self.assertEqual(reason, "contains_url")

    def test_https_url_rejected(self):
        cleaned, reason = engagement_topics._sanitize_question("Check this https://example.com?", 120, True)
        self.assertIsNone(cleaned)
        self.assertEqual(reason, "contains_url")

    def test_fallbacks_are_simple_and_safe(self):
        for text in engagement_topics.SEED_FALLBACKS.values():
            cleaned, reason = engagement_topics._sanitize_question(text, 120, False)
            self.assertIsNotNone(cleaned, msg=f"fallback rejected: {text} reason={reason}")

    async def test_fallback_used_when_ai_fails(self):
        now = datetime.now(timezone.utc)
        sent = types.SimpleNamespace(message_id=10)
        bot = types.SimpleNamespace(send_message=AsyncMock(return_value=sent))
        class Col:
            def find_one(self, *a, **k): return None
            def count_documents(self, *a, **k): return 0
            def find(self, *a, **k): return []
            def insert_one(self, doc): self.doc = doc
        col = Col()
        with patch("app.engagement_topics._history_col", return_value=(col, self._settings(engagement_topic_ai_enabled=True, openai_api_key="x"))), patch("app.engagement_topics._generate_ai_question", side_effect=RuntimeError("boom")), patch("app.engagement_topics._utcnow", return_value=now), patch("app.engagement_topics._acquire_send_lock", return_value=True), patch("app.engagement_topics._release_send_lock"), patch("app.engagement_topics.random.choice", return_value="feature buy opinion"):
            await engagement_topics.run_engagement_topic_job(types.SimpleNamespace(bot=bot))
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(col.doc["source"], "fallback")

    async def test_send_failure_does_not_crash(self):
        now = datetime.now(timezone.utc)
        bot = types.SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("send failed")))
        class Col:
            def find_one(self, *a, **k): return None
            def count_documents(self, *a, **k): return 0
            def find(self, *a, **k): return []
            def insert_one(self, doc): self.doc = doc
        with patch("app.engagement_topics._history_col", return_value=(Col(), self._settings())), patch("app.engagement_topics._utcnow", return_value=now):
            await engagement_topics.run_engagement_topic_job(types.SimpleNamespace(bot=bot))

    async def test_naive_datetime_interval_skip(self):
        now = datetime.now(timezone.utc)
        naive_recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        col = types.SimpleNamespace(find_one=lambda *a, **k: {"sent_at": naive_recent}, count_documents=lambda *a, **k: 0)
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        with patch("app.engagement_topics._history_col", return_value=(col, self._settings())), patch("app.engagement_topics._utcnow", return_value=now), patch("app.engagement_topics._acquire_send_lock", return_value=True), patch("app.engagement_topics._release_send_lock"):
            await engagement_topics.run_engagement_topic_job(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_lock_not_acquired_skips_send(self):
        now = datetime.now(timezone.utc)
        col = types.SimpleNamespace(find_one=lambda *a, **k: None, count_documents=lambda *a, **k: 0)
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        with patch("app.engagement_topics._history_col", return_value=(col, self._settings())), patch("app.engagement_topics._utcnow", return_value=now), patch("app.engagement_topics._acquire_send_lock", return_value=False):
            await engagement_topics.run_engagement_topic_job(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_lock_acquired_allows_send(self):
        now = datetime.now(timezone.utc)
        sent = types.SimpleNamespace(message_id=99)
        bot = types.SimpleNamespace(send_message=AsyncMock(return_value=sent))
        class Col:
            def find_one(self, *a, **k): return None
            def count_documents(self, *a, **k): return 0
            def find(self, *a, **k): return []
            def insert_one(self, doc): self.doc = doc
        col = Col()
        with patch("app.engagement_topics._history_col", return_value=(col, self._settings())), patch("app.engagement_topics._utcnow", return_value=now), patch("app.engagement_topics._acquire_send_lock", return_value=True), patch("app.engagement_topics._release_send_lock"):
            await engagement_topics.run_engagement_topic_job(types.SimpleNamespace(bot=bot))
        self.assertEqual(bot.send_message.await_count, 1)

    def test_scheduler_registration_exists(self):
        class JQ:
            def __init__(self): self.calls=[]
            def run_repeating(self, *a, **k): self.calls.append((a,k))
        app=types.SimpleNamespace(job_queue=JQ())
        with patch("app.engagement_topics.get_settings", return_value=self._settings()):
            with patch("app.engagement_topics.ensure_engagement_topic_indexes"):
                engagement_topics.register_engagement_topic_job(app)
        self.assertEqual(len(app.job_queue.calls),1)
