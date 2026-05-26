import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app import engagement_posts


class EngagementPostsTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self, **kwargs):
        base = dict(
            engagement_posts_enabled=True,
            engagement_posts_dry_run=False,
            engagement_target_chat_ids=[1001],
            engagement_timezone="Asia/Kuala_Lumpur",
            engagement_daily_max_posts=4,
            engagement_min_gap_minutes=120,
            engagement_inactivity_revive_enabled=False,
            engagement_inactivity_minutes=120,
            engagement_revive_cooldown_minutes=360,
            engagement_native_polls_enabled=True,
            engagement_default_disable_notification=False,
            engagement_quiet_hours_enabled=True,
            engagement_quiet_start_hour=2,
            engagement_quiet_end_hour=8,
            engagement_revive_daily_max_posts=1,
            engagement_scheduler_jitter_seconds=300,
        )
        base.update(kwargs)
        return types.SimpleNamespace(**base)

    async def test_feature_flag_off(self):
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock(), send_poll=AsyncMock()))
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_posts_enabled=False)):
            await engagement_posts.run_engagement_posts_tick(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_dry_run_records(self):
        now = datetime(2026, 5, 26, 1, tzinfo=timezone.utc)
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_posts_dry_run=True, engagement_quiet_hours_enabled=False)), patch("app.engagement_posts._utcnow", return_value=now), patch("app.engagement_posts._recent_sent_count", return_value=0), patch("app.engagement_posts._last_sent", return_value=None), patch("app.engagement_posts._get_eligible_prompt", return_value=engagement_posts.PROMPTS[0]), patch("app.engagement_posts.get_db", return_value={"engagement_posts": types.SimpleNamespace(insert_one=lambda doc: setattr(self, "doc", doc)), "community_chat_activity": types.SimpleNamespace(update_one=lambda *a, **k: None)}):
            await engagement_posts.run_engagement_posts_tick(types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock())))
        self.assertEqual(self.doc["status"], "dry_run")

    async def test_daily_max_skip_scheduled(self):
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_quiet_hours_enabled=False)), patch("app.engagement_posts._utcnow", return_value=datetime(2026, 5, 26, 1, tzinfo=timezone.utc)), patch("app.engagement_posts._recent_sent_count", return_value=4):
            ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
            await engagement_posts.run_engagement_posts_tick(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_min_gap_skip(self):
        now = datetime(2026, 5, 26, 1, tzinfo=timezone.utc)
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_quiet_hours_enabled=False)), patch("app.engagement_posts._utcnow", return_value=now), patch("app.engagement_posts._recent_sent_count", return_value=0), patch("app.engagement_posts._last_sent", return_value={"sent_at": now - timedelta(minutes=30)}):
            ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
            await engagement_posts.run_engagement_posts_tick(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    def test_prompt_repeat_guard(self):
        now = datetime.now(timezone.utc)
        class Col:
            def find(self, *a, **k): return [{"prompt_id": "emoji_energy"}]
        with patch("app.engagement_posts.get_db", return_value={"engagement_posts": Col()}), patch("app.engagement_posts.random.choice", side_effect=lambda x: x[0]):
            p = engagement_posts._get_eligible_prompt(1, "scheduled", now)
        self.assertNotEqual(p.prompt_id, "emoji_energy")

    def test_prompt_library_contains_new_prompts(self):
        ids = {p.prompt_id for p in engagement_posts.PROMPTS}
        self.assertIn("emoji_session_mood", ids)
        self.assertIn("poll_play_style", ids)
        self.assertIn("word_luck", ids)

    async def test_text_send_success(self):
        now = datetime.now(timezone.utc)
        bot = types.SimpleNamespace(send_message=AsyncMock(return_value=types.SimpleNamespace(message_id=77)), send_poll=AsyncMock())
        post_col = types.SimpleNamespace(insert_one=lambda doc: setattr(self, "doc", doc))
        with patch("app.engagement_posts.get_db", return_value={"engagement_posts": post_col, "community_chat_activity": types.SimpleNamespace(update_one=lambda *a, **k: None)}):
            await engagement_posts._attempt_send(types.SimpleNamespace(bot=bot), 1001, engagement_posts.PROMPTS[0], self._settings(), source="scheduled", now=now, date_key="2026-05-26")
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(self.doc["status"], "sent")

    async def test_poll_send_success(self):
        now = datetime.now(timezone.utc)
        bot = types.SimpleNamespace(send_message=AsyncMock(), send_poll=AsyncMock(return_value=types.SimpleNamespace(message_id=88)))
        post_col = types.SimpleNamespace(insert_one=lambda doc: setattr(self, "doc", doc))
        with patch("app.engagement_posts.get_db", return_value={"engagement_posts": post_col, "community_chat_activity": types.SimpleNamespace(update_one=lambda *a, **k: None)}):
            await engagement_posts._attempt_send(types.SimpleNamespace(bot=bot), 1001, engagement_posts.PROMPTS[6], self._settings(), source="scheduled", now=now, date_key="2026-05-26")
        self.assertEqual(bot.send_poll.await_count, 1)

    async def test_send_failure_caught(self):
        now = datetime.now(timezone.utc)
        bot = types.SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("boom")), send_poll=AsyncMock())
        post_col = types.SimpleNamespace(insert_one=lambda doc: setattr(self, "doc", doc))
        with patch("app.engagement_posts.get_db", return_value={"engagement_posts": post_col, "community_chat_activity": types.SimpleNamespace(update_one=lambda *a, **k: None)}):
            await engagement_posts._attempt_send(types.SimpleNamespace(bot=bot), 1001, engagement_posts.PROMPTS[0], self._settings(), source="scheduled", now=now, date_key="2026-05-26")
        self.assertEqual(self.doc["status"], "failed")

    async def test_revive_disabled(self):
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_inactivity_revive_enabled=False)):
            await engagement_posts.run_engagement_inactivity_revive_tick(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    async def test_revive_daily_max_blocks(self):
        now = datetime(2026, 5, 26, 1, tzinfo=timezone.utc)
        bot = types.SimpleNamespace(send_message=AsyncMock(return_value=types.SimpleNamespace(message_id=33)), send_poll=AsyncMock())
        activity_col = types.SimpleNamespace(find_one=lambda q: {"chat_id": 1001, "last_message_at": now - timedelta(minutes=240), "last_revive_post_at": now - timedelta(minutes=400)}, update_one=lambda *a, **k: None)

        def count(chat_id, date_key, source=None):
            if source == "revive":
                return 1
            return 0

        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_inactivity_revive_enabled=True, engagement_quiet_hours_enabled=False)), patch("app.engagement_posts._utcnow", return_value=now), patch("app.engagement_posts._recent_sent_count", side_effect=count), patch("app.engagement_posts._get_eligible_prompt", return_value=engagement_posts.REVIVE_PROMPTS[0]), patch("app.engagement_posts.get_db", return_value={"engagement_posts": types.SimpleNamespace(insert_one=lambda doc: setattr(self, "doc", doc)), "community_chat_activity": activity_col}):
            await engagement_posts.run_engagement_inactivity_revive_tick(types.SimpleNamespace(bot=bot))
        self.assertEqual(bot.send_message.await_count, 0)

    async def test_quiet_hours_blocks_scheduled_and_revive(self):
        now = datetime(2026, 5, 26, 18, tzinfo=timezone.utc)  # 02:00 MYT
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock(), send_poll=AsyncMock()))
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_inactivity_revive_enabled=True)), patch("app.engagement_posts._utcnow", return_value=now):
            await engagement_posts.run_engagement_posts_tick(ctx)
            await engagement_posts.run_engagement_inactivity_revive_tick(ctx)
        self.assertEqual(ctx.bot.send_message.await_count, 0)

    def test_quiet_hours_overnight_logic(self):
        settings = self._settings(engagement_quiet_start_hour=22, engagement_quiet_end_hour=8)
        dt_quiet = datetime(2026, 5, 26, 16, tzinfo=timezone.utc)  # 00:00 MYT
        dt_not_quiet = datetime(2026, 5, 26, 3, tzinfo=timezone.utc)  # 11:00 MYT
        self.assertTrue(engagement_posts._is_quiet_hours(dt_quiet, settings))
        self.assertFalse(engagement_posts._is_quiet_hours(dt_not_quiet, settings))

    async def test_tick_does_not_call_ensure_indexes(self):
        now = datetime(2026, 5, 26, 1, tzinfo=timezone.utc)
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_quiet_hours_enabled=False)), patch("app.engagement_posts._utcnow", return_value=now), patch("app.engagement_posts._recent_sent_count", return_value=4), patch("app.engagement_posts.ensure_engagement_indexes") as ensure_idx:
            await engagement_posts.run_engagement_posts_tick(types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock())))
        self.assertEqual(ensure_idx.call_count, 0)


    def test_register_jobs_missing_job_queue_does_not_crash(self):
        app = types.SimpleNamespace(job_queue=None)
        with patch("app.engagement_posts.get_settings", return_value=self._settings()), patch("app.engagement_posts.logger.warning") as warn, patch("app.engagement_posts.ensure_engagement_indexes") as ensure_idx:
            engagement_posts.register_engagement_jobs(app)
        self.assertEqual(ensure_idx.call_count, 0)
        self.assertEqual(warn.call_count, 1)

    def test_register_jobs_disabled_exits_early_even_if_job_queue_missing(self):
        app = types.SimpleNamespace(job_queue=None)
        with patch("app.engagement_posts.get_settings", return_value=self._settings(engagement_posts_enabled=False)), patch("app.engagement_posts.logger.warning") as warn, patch("app.engagement_posts.ensure_engagement_indexes") as ensure_idx:
            engagement_posts.register_engagement_jobs(app)
        self.assertEqual(ensure_idx.call_count, 0)
        self.assertEqual(warn.call_count, 0)

    def test_register_jobs_independent_and_jitter_supported(self):
        class JQ:
            def __init__(self): self.calls=[]
            def get_jobs_by_name(self, name): return []
            def run_repeating(self, callback, interval, first, name, jitter=None): self.calls.append({"name": name, "jitter": jitter})
        app = types.SimpleNamespace(job_queue=JQ())
        with patch("app.engagement_posts.get_settings", return_value=self._settings()), patch("app.engagement_posts.ensure_engagement_indexes"):
            engagement_posts.register_engagement_jobs(app)
        self.assertEqual(len(app.job_queue.calls), 2)
        self.assertEqual({c["name"] for c in app.job_queue.calls}, {"engagement_posts_tick", "engagement_inactivity_revive_tick"})
        self.assertTrue(all(c["jitter"] == 300 for c in app.job_queue.calls))

    def test_register_jobs_when_posts_exists_still_registers_revive(self):
        class JQ:
            def __init__(self): self.calls=[]
            def get_jobs_by_name(self, name):
                if name == "engagement_posts_tick":
                    return [object()]
                return []
            def run_repeating(self, callback, interval, first, name, jitter=None): self.calls.append(name)
        app = types.SimpleNamespace(job_queue=JQ())
        with patch("app.engagement_posts.get_settings", return_value=self._settings()), patch("app.engagement_posts.ensure_engagement_indexes"):
            engagement_posts.register_engagement_jobs(app)
        self.assertEqual(app.job_queue.calls, ["engagement_inactivity_revive_tick"])

    def test_register_jobs_jitter_fallback_when_unsupported(self):
        class JQ:
            def __init__(self): self.calls=[]
            def get_jobs_by_name(self, name): return []
            def run_repeating(self, callback, interval, first, name): self.calls.append(name)
        app = types.SimpleNamespace(job_queue=JQ())
        with patch("app.engagement_posts.get_settings", return_value=self._settings()), patch("app.engagement_posts.ensure_engagement_indexes"):
            engagement_posts.register_engagement_jobs(app)
        self.assertEqual(set(app.job_queue.calls), {"engagement_posts_tick", "engagement_inactivity_revive_tick"})

    def test_record_chat_activity(self):
        now = datetime.now(timezone.utc)
        calls = {}
        col = types.SimpleNamespace(update_one=lambda *a, **k: calls.update({"args": a, "kwargs": k}))
        with patch("app.engagement_posts.get_db", return_value={"community_chat_activity": col}), patch("app.engagement_posts._utcnow", return_value=now):
            engagement_posts.record_chat_activity(chat_id=1001, message_at=now)
        self.assertEqual(calls["args"][0]["chat_id"], 1001)
