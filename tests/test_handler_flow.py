import types
import unittest
from unittest.mock import AsyncMock, patch

from app import handlers
from app.classifier import classify
from app.reply_policy import ReplyPolicyResult
from app.responses import generate_reply, get_reaction
from app.seed_rotation import SeedItem, SeedRotationService


class DummyUser:
    def __init__(self, user_id=123, is_bot=False, username="user"):
        self.id = user_id
        self.is_bot = is_bot
        self.username = username


class DummyMessage:
    def __init__(self, text, user=None):
        self.text = text
        self.chat_id = 999
        self.message_id = 1001
        self.from_user = user or DummyUser()
        self.reply_text = AsyncMock()


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
        admin_chat_id=None,
    )
    payload.update(kwargs)
    return types.SimpleNamespace(**payload)


class HandlerFlowTests(unittest.IsolatedAsyncioTestCase):
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
