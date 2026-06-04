import types
import unittest
from unittest.mock import AsyncMock, patch

from app import handlers
from app.classifier import classify
from app.reply_policy import ReplyPolicyResult
from app.responses import generate_reply, get_reaction
from app.seed_rotation import SeedItem, SeedRotationService
from telegram.error import BadRequest


class DummyUser:
    def __init__(self, user_id=123, is_bot=False, username="user"):
        self.id = user_id
        self.is_bot = is_bot
        self.username = username


class DummyMessage:
    def __init__(self, text=None, user=None, caption=None, chat_type="group"):
        self.text = text
        self.caption = caption
        self.chat_id = 999
        self.chat = types.SimpleNamespace(type=chat_type) if chat_type else None
        self.message_id = 1001
        self.from_user = user or DummyUser()
        self.reply_text = AsyncMock()
        self.reply_photo = AsyncMock()


def make_settings(**kwargs):
    payload = dict(
        enable_tagging=True,
        enable_suggestions=False,
        enable_low_risk_auto_reply=True,
        enable_threaded_replies=True,
        enable_auto_reply_throttle=True,
        enable_ai_decision=True,
        enable_ai_generation=True,
        enable_ai_moderation=True,
        openai_api_key="x",
        openai_decision_model="gpt-4.1-mini",
        openai_generation_model="gpt-4.1-mini",
        ai_decision_confidence_threshold=0.82,
        ai_rule_threshold=0.88,
        ai_ambiguous_categories=["win_share", "positive_signal", "unknown"],
        ai_max_reply_chars=220,
        ai_generation_allowed_categories=["win_share", "new_user"],
        ai_seed_only_categories=["support_issue", "voucher_question"],
        ai_priority_categories=["new_user", "support_issue", "voucher_question", "win_share"],
        ai_max_decisions_per_minute=50,
        ai_max_generations_per_minute=20,
        ai_max_decisions_per_chat_per_hour=120,
        ai_enable_budget_downgrade=True,
        ai_seed_repeat_window_seconds=300,
        ai_max_seed_reuse_per_window=1,
        ai_generation_rewrite_mode=True,
        enable_seed_rotation_memory=True,
        community_helper_enabled=False,
        admin_chat_id=None,
    )
    payload.update(kwargs)
    return types.SimpleNamespace(**payload)


class HandlerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_contains_cyrillic_detects_unicode_range(self):
        self.assertTrue(handlers.contains_cyrillic("hello Привет"))
        self.assertFalse(handlers.contains_cyrillic("hello world"))

    async def test_non_admin_russian_text_is_deleted(self):
        update = types.SimpleNamespace(message=DummyMessage("Привет бонус"))
        bot = types.SimpleNamespace(
            id=42,
            delete_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=types.SimpleNamespace(status="member")),
        )
        context = types.SimpleNamespace(bot=bot)

        with self.assertLogs("app.handlers", level="INFO") as logs:
            await handlers.message_handler(update, context)

        bot.delete_message.assert_awaited_once_with(chat_id=999, message_id=1001)
        self.assertIn(
            "[MODERATION_DELETE] reason=cyrillic_language user_id=123 chat_id=999 message_id=1001",
            "\n".join(logs.output),
        )

    async def test_non_admin_mixed_english_cyrillic_is_deleted(self):
        update = types.SimpleNamespace(message=DummyMessage("bonus Привет"))
        bot = types.SimpleNamespace(
            id=42,
            delete_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=types.SimpleNamespace(status="member")),
        )
        context = types.SimpleNamespace(bot=bot)

        await handlers.message_handler(update, context)

        bot.delete_message.assert_awaited_once_with(chat_id=999, message_id=1001)

    async def test_admin_cyrillic_message_is_not_deleted(self):
        update = types.SimpleNamespace(message=DummyMessage("Привет админ"))
        bot = types.SimpleNamespace(
            id=42,
            delete_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=types.SimpleNamespace(status="administrator")),
        )
        context = types.SimpleNamespace(bot=bot)

        decision = types.SimpleNamespace(category="unknown", action="ignore", confidence=0.2, suggested_reply="", reason="rule")
        settings = make_settings(enable_ai_decision=False)

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=decision), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(bot.delete_message.await_count, 0)

    async def test_private_chat_cyrillic_message_is_not_deleted(self):
        update = types.SimpleNamespace(message=DummyMessage("Привет", chat_type="private"))
        bot = types.SimpleNamespace(
            id=42,
            delete_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=types.SimpleNamespace(status="member")),
        )
        context = types.SimpleNamespace(bot=bot, send_message=AsyncMock())
        decision = types.SimpleNamespace(category="unknown", action="ignore", confidence=0.2, suggested_reply="", reason="rule")
        settings = make_settings(enable_ai_decision=False)

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=decision), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(bot.delete_message.await_count, 0)

    async def test_normal_english_message_is_not_deleted(self):
        update = types.SimpleNamespace(message=DummyMessage("hello bonus"))
        bot = types.SimpleNamespace(
            id=42,
            delete_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=types.SimpleNamespace(status="member")),
        )
        context = types.SimpleNamespace(bot=bot, send_message=AsyncMock(), set_message_reaction=AsyncMock())
        decision = types.SimpleNamespace(category="unknown", action="ignore", confidence=0.2, suggested_reply="", reason="rule")
        settings = make_settings(enable_ai_decision=False)

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=decision), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(bot.delete_message.await_count, 0)

    async def test_cyrillic_caption_is_deleted_by_caption_moderation_handler(self):
        update = types.SimpleNamespace(message=DummyMessage(text=None, caption="promo Привет"))
        bot = types.SimpleNamespace(
            id=42,
            delete_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=types.SimpleNamespace(status="member")),
        )
        context = types.SimpleNamespace(bot=bot)

        await handlers.cyrillic_caption_moderation_handler(update, context)

        bot.delete_message.assert_awaited_once_with(chat_id=999, message_id=1001)

    async def test_cyrillic_delete_failure_logs_warning_without_crash(self):
        update = types.SimpleNamespace(message=DummyMessage("Привет"))
        bot = types.SimpleNamespace(
            id=42,
            delete_message=AsyncMock(side_effect=RuntimeError("missing permission")),
            get_chat_member=AsyncMock(return_value=types.SimpleNamespace(status="member")),
        )
        context = types.SimpleNamespace(bot=bot)

        with self.assertLogs("app.handlers", level="WARNING") as logs:
            await handlers.message_handler(update, context)

        self.assertIn("[MODERATION_DELETE_FAILED] reason=cyrillic_language error=missing permission", "\n".join(logs.output))

    async def test_safe_add_reaction_skips_reaction_invalid(self):
        bot = types.SimpleNamespace(set_message_reaction=AsyncMock(side_effect=BadRequest("Reaction_invalid")))

        with self.assertLogs("app.handlers", level="INFO") as logs:
            result = await handlers.safe_add_reaction(
                bot=bot,
                chat_id=999,
                message_id=1001,
                emoji="🔥",
                flow="unit_test",
            )

        self.assertFalse(result)
        self.assertIn("reaction_invalid_skipped chat_id=999 message_id=1001 emoji=🔥", logs.output[0])

    async def test_deterministic_new_user_still_sends(self):
        settings = make_settings(enable_ai_decision=False)
        update = types.SimpleNamespace(message=DummyMessage("hi im new"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        decision = types.SimpleNamespace(category="new_user", action="auto_reply", confidence=0.95, suggested_reply="", reason="rule")
        throttle_allow = types.SimpleNamespace(allowed=True, reason="none", normalized_text_hash="h")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=decision), patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_allow), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 1)
        _, kwargs = update.message.reply_text.await_args
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertIsNotNone(kwargs.get("reply_markup"))

    async def test_deterministic_support_behaves(self):
        settings = make_settings(enable_ai_decision=False, enable_suggestions=True, admin_chat_id=123)
        update = types.SimpleNamespace(message=DummyMessage("voucher code not working"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        decision = types.SimpleNamespace(category="support_issue", action="suggest_only", confidence=0.8, suggested_reply="Please share UID", reason="rule")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=decision), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(context.bot.send_message.await_count, 1)
        self.assertEqual(update.message.reply_text.await_count, 0)

    async def test_ai_ambiguous_win_share_runs_and_sends_once(self):
        settings = make_settings()
        update = types.SimpleNamespace(message=DummyMessage("daily recommendation but i won 500x"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        rule_decision = types.SimpleNamespace(category="win_share", action="auto_reply", confidence=0.95, suggested_reply="", reason="rule")
        throttle_allow = types.SimpleNamespace(allowed=True, reason="none", normalized_text_hash="h")
        ai_decision = types.SimpleNamespace(
            category="win_share",
            confidence=0.95,
            should_reply=True,
            tone="celebratory",
            reply_goal="celebrate",
            suggested_reply_style="celebratory_short",
            safety_risk="low",
            is_low_value_noise=False,
        )
        policy = ReplyPolicyResult(
            mode="rewrite",
            should_send=True,
            reason="allow",
            category="win_share",
            seed_candidates=[SeedItem(key="k1", text="Nice hit!", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",))],
        )
        ai_client = types.SimpleNamespace(moderate=lambda _: False)
        ai_decision_service = types.SimpleNamespace(decide=lambda _: ai_decision)
        ai_reply_service = types.SimpleNamespace(generate=lambda **_: "Great win, congrats!")
        reply_policy = types.SimpleNamespace(evaluate=lambda _: policy)
        decision_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")
        generation_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=rule_decision), patch("app.handlers._get_ai_runtime", return_value=(ai_client, ai_decision_service, ai_reply_service, reply_policy)), patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_allow), patch("app.handlers.ai_budget_service.allow_decision", return_value=decision_budget), patch("app.handlers.ai_budget_service.allow_generation", return_value=generation_budget), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 1)

    async def test_ambiguous_win_share_routes_to_ai(self):
        settings = make_settings()
        self.assertTrue(
            handlers._should_run_ai_decision(
                settings=settings,
                category="win_share",
                confidence=0.95,
                text="I won 500x today",
            )
        )

    async def test_budget_exhaustion_downgrades_to_seed(self):
        settings = make_settings()
        update = types.SimpleNamespace(message=DummyMessage("daily recommendation and win post"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        rule_decision = types.SimpleNamespace(category="win_share", action="auto_reply", confidence=0.95, suggested_reply="", reason="rule")
        throttle_allow = types.SimpleNamespace(allowed=True, reason="none", normalized_text_hash="h")
        ai_decision = types.SimpleNamespace(
            category="win_share",
            confidence=0.95,
            should_reply=True,
            tone="celebratory",
            reply_goal="celebrate",
            suggested_reply_style="celebratory_short",
            safety_risk="low",
            is_low_value_noise=False,
        )
        policy = ReplyPolicyResult(
            mode="rewrite",
            should_send=True,
            reason="allow",
            category="win_share",
            seed_candidates=[SeedItem(key="k1", text="Nice hit!", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",))],
        )
        ai_client = types.SimpleNamespace(moderate=lambda _: False)
        ai_decision_service = types.SimpleNamespace(decide=lambda _: ai_decision)
        ai_reply_service = types.SimpleNamespace(generate=lambda **_: "Should not be used")
        reply_policy = types.SimpleNamespace(evaluate=lambda _: policy)
        decision_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")
        generation_budget = types.SimpleNamespace(allowed=False, state="downgrade", reason="global_generation_limit")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=rule_decision), patch("app.handlers._get_ai_runtime", return_value=(ai_client, ai_decision_service, ai_reply_service, reply_policy)), patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_allow), patch("app.handlers.ai_budget_service.allow_decision", return_value=decision_budget), patch("app.handlers.ai_budget_service.allow_generation", return_value=generation_budget), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 1)

    async def test_rewrite_exception_falls_back_to_seed(self):
        settings = make_settings()
        update = types.SimpleNamespace(message=DummyMessage("daily recommendation and win post"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        rule_decision = types.SimpleNamespace(category="win_share", action="auto_reply", confidence=0.95, suggested_reply="", reason="rule")
        throttle_allow = types.SimpleNamespace(allowed=True, reason="none", normalized_text_hash="h")
        ai_decision = types.SimpleNamespace(
            category="win_share",
            confidence=0.95,
            should_reply=True,
            tone="celebratory",
            reply_goal="celebrate",
            suggested_reply_style="celebratory_short",
            safety_risk="low",
            is_low_value_noise=False,
        )
        seed = SeedItem(key="k1", text="Nice hit! Great one", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",))
        policy = ReplyPolicyResult(mode="rewrite", should_send=True, reason="allow", category="win_share", seed_candidates=[seed])
        ai_client = types.SimpleNamespace(moderate=lambda _: False)
        ai_decision_service = types.SimpleNamespace(decide=lambda _: ai_decision)
        ai_reply_service = types.SimpleNamespace(generate=lambda **_: (_ for _ in ()).throw(RuntimeError("boom")))
        reply_policy = types.SimpleNamespace(evaluate=lambda _: policy)
        decision_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")
        generation_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=rule_decision), patch("app.handlers._get_ai_runtime", return_value=(ai_client, ai_decision_service, ai_reply_service, reply_policy)), patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_allow), patch("app.handlers.ai_budget_service.allow_decision", return_value=decision_budget), patch("app.handlers.ai_budget_service.allow_generation", return_value=generation_budget), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 1)
        args, _ = update.message.reply_text.await_args
        self.assertEqual(args[0], seed.text)

    async def test_rewrite_empty_falls_back_to_seed(self):
        settings = make_settings()
        update = types.SimpleNamespace(message=DummyMessage("daily recommendation and win post"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        rule_decision = types.SimpleNamespace(category="win_share", action="auto_reply", confidence=0.95, suggested_reply="", reason="rule")
        throttle_allow = types.SimpleNamespace(allowed=True, reason="none", normalized_text_hash="h")
        ai_decision = types.SimpleNamespace(
            category="win_share",
            confidence=0.95,
            should_reply=True,
            tone="celebratory",
            reply_goal="celebrate",
            suggested_reply_style="celebratory_short",
            safety_risk="low",
            is_low_value_noise=False,
        )
        seed = SeedItem(key="k1", text="Nice hit! Great one", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",))
        policy = ReplyPolicyResult(mode="rewrite", should_send=True, reason="allow", category="win_share", seed_candidates=[seed])
        ai_client = types.SimpleNamespace(moderate=lambda _: False)
        ai_decision_service = types.SimpleNamespace(decide=lambda _: ai_decision)
        ai_reply_service = types.SimpleNamespace(generate=lambda **_: "")
        reply_policy = types.SimpleNamespace(evaluate=lambda _: policy)
        decision_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")
        generation_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=rule_decision), patch("app.handlers._get_ai_runtime", return_value=(ai_client, ai_decision_service, ai_reply_service, reply_policy)), patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_allow), patch("app.handlers.ai_budget_service.allow_decision", return_value=decision_budget), patch("app.handlers.ai_budget_service.allow_generation", return_value=generation_budget), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 1)
        args, _ = update.message.reply_text.await_args
        self.assertEqual(args[0], seed.text)

    async def test_budget_blocks_low_priority_decision(self):
        settings = make_settings(ai_priority_categories=["support_issue"])
        update = types.SimpleNamespace(message=DummyMessage("random text"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        rule_decision = types.SimpleNamespace(category="unknown", action="ignore", confidence=0.2, suggested_reply="", reason="rule")
        decision_budget = types.SimpleNamespace(allowed=False, state="deny", reason="global_decision_limit")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=rule_decision), patch("app.handlers._get_ai_runtime", return_value=(object(), object(), object(), object())), patch("app.handlers.ai_budget_service.allow_decision", return_value=decision_budget), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 0)

    async def test_moderation_block_stops_send(self):
        settings = make_settings()
        update = types.SimpleNamespace(message=DummyMessage("daily recommendation and win"))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock()))
        rule_decision = types.SimpleNamespace(category="win_share", action="auto_reply", confidence=0.95, suggested_reply="", reason="rule")
        ai_decision = types.SimpleNamespace(
            category="win_share",
            confidence=0.95,
            should_reply=True,
            tone="celebratory",
            reply_goal="celebrate",
            suggested_reply_style="celebratory_short",
            safety_risk="low",
            is_low_value_noise=False,
        )
        policy = ReplyPolicyResult(
            mode="rewrite",
            should_send=True,
            reason="allow",
            category="win_share",
            seed_candidates=[SeedItem(key="k1", text="Nice hit!", tone="celebratory", reply_goal="celebrate", allowed_contexts=("group",))],
        )
        ai_client = types.SimpleNamespace(moderate=lambda _: True)
        ai_decision_service = types.SimpleNamespace(decide=lambda _: ai_decision)
        ai_reply_service = types.SimpleNamespace(generate=lambda **_: "Great win, congrats!")
        reply_policy = types.SimpleNamespace(evaluate=lambda _: policy)
        decision_budget = types.SimpleNamespace(allowed=True, state="allow", reason="ok")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.classify_message", return_value=rule_decision), patch("app.handlers._get_ai_runtime", return_value=(ai_client, ai_decision_service, ai_reply_service, reply_policy)), patch("app.handlers.ai_budget_service.allow_decision", return_value=decision_budget), patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 0)

    async def test_bot_self_non_text_ignored(self):
        settings = make_settings()
        update = types.SimpleNamespace(message=DummyMessage("hello", user=DummyUser(is_bot=True)))
        context = types.SimpleNamespace(bot=types.SimpleNamespace(id=42))
        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.log_message") as log_mock:
            await handlers.message_handler(update, context)
        self.assertFalse(log_mock.called)

    def test_seed_rotation_avoids_immediate_repetition(self):
        service = SeedRotationService()
        seeds = [
            SeedItem(key="a", text="a", tone="t", reply_goal="g", allowed_contexts=("group",)),
            SeedItem(key="b", text="b", tone="t", reply_goal="g", allowed_contexts=("group",)),
        ]
        first = service.pick_seed(chat_id=1, category="win_share", seeds=seeds, repeat_window_seconds=300, max_seed_reuse_per_window=1)
        service.mark_used(chat_id=1, category="win_share", seed_key=first.key)
        second = service.pick_seed(chat_id=1, category="win_share", seeds=seeds, repeat_window_seconds=300, max_seed_reuse_per_window=1)
        self.assertNotEqual(first.key, second.key)

    def test_recommendation_text_not_win_share(self):
        self.assertNotEqual(classify("this game has 100000x max win recommended"), "win_share")

    def test_real_win_share_still_detected(self):
        self.assertEqual(classify("I won 500x and cashed out"), "win_share")

    def test_mixed_intent_triggers_ai(self):
        settings = make_settings()
        self.assertTrue(handlers.has_mixed_intent("I won 500x but this game has 9600 max win"))
        self.assertTrue(
            handlers.should_run_ai_decision(
                settings=settings,
                text="I won 500x but this game has 9600 max win",
                rule_category="win_share",
                rule_confidence=0.95,
            )
        )

    def test_voucher_subscription_classified(self):
        self.assertEqual(
            classify("New vouchers drop regularly. Stay subscribed to channel to get them."),
            "voucher_subscription",
        )

    def test_voucher_drop_announcement_classified(self):
        self.assertEqual(classify("vouchers drop every week, don't miss out!"), "voucher_subscription")

    def test_stay_subscribed_classified(self):
        self.assertEqual(classify("Stay subscribed for the latest drops"), "voucher_subscription")

    def test_comeback_campaign_classified(self):
        self.assertEqual(classify("#comebackisreal"), "comeback_campaign")
        self.assertEqual(classify("comebackisreal"), "comeback_campaign")
        self.assertEqual(classify("Come Back Is Real"), "comeback_campaign")
        self.assertEqual(classify("wow #ComeBackIsReal today"), "comeback_campaign")

    def test_comeback_campaign_reaction_and_reply_payload(self):
        self.assertEqual(get_reaction("comeback_campaign"), "🔥")
        self.assertEqual(generate_reply("comeback_campaign", "#comebackisreal"), "")

    def test_comeback_alone_not_classified(self):
        self.assertNotEqual(classify("What a comeback from the team"), "comeback_campaign")

    def test_real_new_user_still_detected(self):
        self.assertEqual(classify("hi im new here"), "new_user")

    def test_voucher_support_question_not_subscription(self):
        result = classify("my voucher code is not working")
        self.assertNotEqual(result, "voucher_subscription")

    async def test_voucher_subscription_auto_replies(self):
        settings = make_settings(enable_ai_decision=False)
        update = types.SimpleNamespace(
            message=DummyMessage("New vouchers drop regularly. Stay subscribed to channel to get them.")
        )
        context = types.SimpleNamespace(
            bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock())
        )
        decision = types.SimpleNamespace(
            category="voucher_subscription",
            action="auto_reply",
            confidence=0.95,
            suggested_reply="",
            reason="rule",
        )
        throttle_allow = types.SimpleNamespace(allowed=True, reason="none", normalized_text_hash="h")

        with patch("app.handlers.get_settings", return_value=settings), \
             patch("app.handlers.classify_message", return_value=decision), \
             patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_allow), \
             patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(update.message.reply_text.await_count, 1)

    async def test_comeback_campaign_adds_reaction_without_reply(self):
        settings = make_settings(enable_ai_decision=False)
        update = types.SimpleNamespace(message=DummyMessage("#comebackisreal"))
        context = types.SimpleNamespace(
            bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock())
        )
        decision = types.SimpleNamespace(
            category="comeback_campaign",
            action="auto_reply",
            confidence=0.95,
            suggested_reply="",
            reason="rule",
        )
        throttle_allow = types.SimpleNamespace(allowed=True, reason="none", normalized_text_hash="h")

        with patch("app.handlers.get_settings", return_value=settings), \
             patch("app.handlers.classify_message", return_value=decision), \
             patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_allow), \
             patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(context.bot.set_message_reaction.await_count, 1)
        self.assertEqual(update.message.reply_text.await_count, 0)

    async def test_comeback_campaign_reacts_even_when_throttle_blocks_reply(self):
        settings = make_settings(enable_ai_decision=False)
        update = types.SimpleNamespace(message=DummyMessage("#comebackisreal"))
        context = types.SimpleNamespace(
            bot=types.SimpleNamespace(id=42, set_message_reaction=AsyncMock(), send_message=AsyncMock())
        )
        decision = types.SimpleNamespace(
            category="comeback_campaign",
            action="auto_reply",
            confidence=0.95,
            suggested_reply="",
            reason="rule",
        )
        throttle_block = types.SimpleNamespace(allowed=False, reason="user_cooldown", normalized_text_hash="h")

        with patch("app.handlers.get_settings", return_value=settings), \
             patch("app.handlers.classify_message", return_value=decision), \
             patch("app.handlers.auto_reply_throttle.evaluate_auto_reply_throttle", return_value=throttle_block), \
             patch("app.handlers.log_message"):
            await handlers.message_handler(update, context)

        self.assertEqual(context.bot.set_message_reaction.await_count, 1)
        self.assertEqual(update.message.reply_text.await_count, 0)
        self.assertEqual(context.bot.send_message.await_count, 0)


if __name__ == "__main__":
    unittest.main()


class WelcomeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_allowed_target_chat_sends_photo_once_and_schedules_delete(self):
        user_one = DummyUser(user_id=1, is_bot=False, username="user_one")
        user_two = DummyUser(user_id=3, is_bot=False, username="user_two")
        bot_user = DummyUser(user_id=2, is_bot=True, username="bot_user")
        sent = types.SimpleNamespace(chat_id=-1002304653063, message_id=2001)
        message = types.SimpleNamespace(
            chat_id=-1002304653063,
            message_id=1001,
            new_chat_members=[user_one, bot_user, user_two],
            reply_photo=AsyncMock(return_value=sent),
            reply_text=AsyncMock(),
        )
        job_queue = types.SimpleNamespace(run_once=unittest.mock.Mock())
        context = types.SimpleNamespace(job_queue=job_queue)
        settings = make_settings(welcome_target_chat_id=-1002304653063, welcome_image_path="assets/ap_welcome.jpg")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.Path.open", unittest.mock.mock_open(read_data=b"img")):
            await handlers.welcome_new_members_handler(types.SimpleNamespace(message=message), context)

        self.assertEqual(message.reply_photo.await_count, 1)
        self.assertEqual(message.reply_text.await_count, 0)
        self.assertEqual(job_queue.run_once.call_count, 1)

    async def test_welcome_skipped_for_non_target_chat(self):
        message = types.SimpleNamespace(
            chat_id=-100999,
            message_id=1001,
            new_chat_members=[DummyUser(user_id=1, is_bot=False, username="user1")],
            reply_photo=AsyncMock(),
            reply_text=AsyncMock(),
        )
        settings = make_settings(welcome_target_chat_id=-1002304653063, welcome_image_path="assets/ap_welcome.jpg")

        with patch("app.handlers.get_settings", return_value=settings):
            await handlers.welcome_new_members_handler(types.SimpleNamespace(message=message), types.SimpleNamespace(job_queue=None))

        self.assertEqual(message.reply_photo.await_count, 0)
        self.assertEqual(message.reply_text.await_count, 0)

    async def test_welcome_photo_failure_falls_back_to_text_and_schedules_delete(self):
        sent = types.SimpleNamespace(chat_id=999, message_id=2001)
        no_username_user = types.SimpleNamespace(
            id=1,
            is_bot=False,
            username=None,
            mention_html=lambda: '<a href="tg://user?id=1">NoName</a>',
        )
        message = types.SimpleNamespace(
            chat_id=999,
            message_id=1001,
            new_chat_members=[no_username_user],
            reply_photo=AsyncMock(side_effect=RuntimeError("photo failed")),
            reply_text=AsyncMock(return_value=sent),
        )
        job_queue = types.SimpleNamespace(run_once=unittest.mock.Mock())
        context = types.SimpleNamespace(job_queue=job_queue)
        settings = make_settings(welcome_target_chat_id=None, welcome_image_path="assets/missing.jpg")

        with patch("app.handlers.get_settings", return_value=settings):
            await handlers.welcome_new_members_handler(types.SimpleNamespace(message=message), context)

        self.assertEqual(message.reply_photo.await_count, 0)
        self.assertEqual(message.reply_text.await_count, 1)
        args, kwargs = message.reply_text.await_args
        self.assertIn('tg://user?id=1', args[0])
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertEqual(job_queue.run_once.call_count, 1)

    async def test_welcome_new_members_mentions_only_first_five_humans(self):
        members = [DummyUser(user_id=i, is_bot=False, username=f"user{i}") for i in range(1, 8)]
        sent = types.SimpleNamespace(chat_id=999, message_id=2001)
        message = types.SimpleNamespace(
            chat_id=999,
            message_id=1001,
            new_chat_members=members,
            reply_photo=AsyncMock(return_value=sent),
            reply_text=AsyncMock(),
        )
        job_queue = types.SimpleNamespace(run_once=unittest.mock.Mock())
        context = types.SimpleNamespace(job_queue=job_queue)
        settings = make_settings(welcome_target_chat_id=None, welcome_image_path="assets/ap_welcome.jpg")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.Path.open", unittest.mock.mock_open(read_data=b"img")):
            await handlers.welcome_new_members_handler(types.SimpleNamespace(message=message), context)

        args, kwargs = message.reply_photo.await_args
        text = kwargs["caption"]
        for i in range(1, 6):
            self.assertIn(f"@user{i}", text)
        self.assertNotIn("@user6", text)
        self.assertNotIn("@user7", text)

    async def test_welcome_reply_photo_failure_falls_back_to_text(self):
        sent = types.SimpleNamespace(chat_id=999, message_id=2001)
        message = types.SimpleNamespace(
            chat_id=999,
            message_id=1001,
            new_chat_members=[DummyUser(user_id=1, is_bot=False, username="user1")],
            reply_photo=AsyncMock(side_effect=RuntimeError("photo failed")),
            reply_text=AsyncMock(return_value=sent),
        )
        context = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=unittest.mock.Mock()))
        settings = make_settings(welcome_target_chat_id=None, welcome_image_path="assets/ap_welcome.jpg")

        with patch("app.handlers.get_settings", return_value=settings), patch("app.handlers.Path.open", unittest.mock.mock_open(read_data=b"img")):
            await handlers.welcome_new_members_handler(types.SimpleNamespace(message=message), context)

        self.assertEqual(message.reply_photo.await_count, 1)
        self.assertEqual(message.reply_text.await_count, 1)

    async def test_delete_message_job_ignores_delete_errors(self):
        bot = types.SimpleNamespace(delete_message=AsyncMock(side_effect=RuntimeError("missing permission")))
        job = types.SimpleNamespace(data={"chat_id": 999, "message_id": 123})
        context = types.SimpleNamespace(job=job, bot=bot)

        await handlers.delete_message_job(context)

        self.assertEqual(bot.delete_message.await_count, 1)
