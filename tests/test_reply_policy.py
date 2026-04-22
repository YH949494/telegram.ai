import unittest

from app.ai_decision import DecisionResult
from app.reply_policy import ReplyPolicyService


class ReplyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ReplyPolicyService(
            confidence_threshold=0.82,
            generation_allowed_categories=["win_share", "new_user"],
            seed_only_categories=["support_issue", "voucher_question"],
        )

    def _decision(self, **kwargs):
        payload = dict(
            should_reply=True,
            category="win_share",
            confidence=0.9,
            reason="x",
            tone="celebratory",
            reply_goal="celebrate",
            safety_risk="low",
            suggested_reply_style="celebratory_short",
            user_intent_summary="x",
            mentions_game_result=True,
            mentions_recommendation=False,
            mentions_support_issue=False,
            mentions_new_user_signal=False,
            is_low_value_noise=False,
        )
        payload.update(kwargs)
        return DecisionResult(**payload)

    def test_recommendation_not_win_share(self):
        d = self._decision(category="game_recommendation", should_reply=False, mentions_recommendation=True)
        r = self.policy.evaluate(d)
        self.assertFalse(r.should_send)

    def test_actual_win_share_allowed(self):
        d = self._decision()
        r = self.policy.evaluate(d)
        self.assertTrue(r.should_send)
        self.assertEqual(r.mode, "rewrite")

    def test_low_confidence_blocked(self):
        d = self._decision(confidence=0.5)
        r = self.policy.evaluate(d)
        self.assertFalse(r.should_send)
        self.assertEqual(r.reason, "low_confidence")

    def test_support_issue_routes(self):
        d = self._decision(category="support_issue", tone="helpful", reply_goal="answer_question", suggested_reply_style="helpful_short")
        r = self.policy.evaluate(d)
        self.assertTrue(r.should_send)
        self.assertEqual(r.mode, "seed")

    def test_unseeded_category_blocked(self):
        d = self._decision(category="general_question", tone="neutral", reply_goal="clarify", suggested_reply_style="short_direct")
        r = self.policy.evaluate(d)
        self.assertFalse(r.should_send)
        self.assertEqual(r.reason, "unseeded_category")


if __name__ == "__main__":
    unittest.main()
