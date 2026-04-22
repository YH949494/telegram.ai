import unittest

from app.ai_decision import DecisionResult


class DecisionModelTests(unittest.TestCase):
    def test_decision_result_schema_fields(self):
        result = DecisionResult(
            should_reply=True,
            category="win_share",
            confidence=0.91,
            reason="strong win signal",
            tone="celebratory",
            reply_goal="celebrate",
            safety_risk="low",
            suggested_reply_style="celebratory_short",
            user_intent_summary="user shares a personal win",
            mentions_game_result=True,
            mentions_recommendation=False,
            mentions_support_issue=False,
            mentions_new_user_signal=False,
            is_low_value_noise=False,
        )
        self.assertTrue(result.should_reply)
        self.assertEqual(result.category, "win_share")

    def test_confidence_bounds(self):
        with self.assertRaises(Exception):
            DecisionResult(
                should_reply=True,
                category="win_share",
                confidence=1.2,
                reason="bad",
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


if __name__ == "__main__":
    unittest.main()
