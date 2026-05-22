import unittest

from app.community_intelligence import (
    classify_community_message,
    message_fingerprint,
    normalize_for_fingerprint,
)


class CommunityIntelligenceTests(unittest.TestCase):
    def _assert_button(self, decision, text, url):
        self.assertTrue(decision.buttons)
        self.assertEqual(decision.buttons[0].text, text)
        self.assertEqual(decision.buttons[0].url, url)

    def test_voucher_where_to_enter_button(self):
        d = classify_community_message("where to enter voucher code?")
        self.assertEqual(d.intent, "voucher_where_to_enter")
        self._assert_button(d, "View Guide", "https://t.me/advantplayofficial/714")

    def test_voucher_code_incorrect_and_not_working(self):
        expected = "The code may be expired, already used, entered incorrectly, or fully claimed. Please check with platform Customer Service for further help."
        d1 = classify_community_message("invalid code")
        self.assertEqual(d1.intent, "voucher_code_incorrect")
        self.assertEqual(d1.reply, expected)
        self._assert_button(d1, "View Guide", "https://t.me/advantplayofficial/714")

        d2 = classify_community_message("code not working!!!")
        self.assertEqual(d2.intent, "voucher_not_working")
        self.assertEqual(d2.reply, expected)
        self._assert_button(d2, "View Guide", "https://t.me/advantplayofficial/714")

    def test_free_spin_guide_buttons(self):
        for text in ["how claim free spin", "redeem free spin in game", "free spin video guide"]:
            d = classify_community_message(text)
            self.assertIn(d.intent, {"free_spin_claim_how", "free_spin_redeem_in_game", "free_spin_video_guide"})
            self.assertEqual(d.reply, "Please follow the Free Spin guide below.")
            self._assert_button(d, "View Guide", "https://t.me/advantplayofficial/714")

    def test_required_other_buttons(self):
        cases = [
            ("i am new user", "new_user_start", "Official Channel", "https://t.me/advantplayofficial"),
            ("how to access mini app", "miniapp_access_how", "Open Mini App", "https://t.me/APreferralV1_bot?start=start"),
            ("how submit mywin", "mywin_submit_how", "Join Community Group", "https://t.me/+tgGbOPvp1p05NjA9"),
            ("how follow official channel", "official_channel_follow_how", "Official Channel", "https://t.me/advantplayofficial"),
        ]
        for text, intent, btn_text, url in cases:
            d = classify_community_message(text)
            self.assertEqual(d.intent, intent)
            self._assert_button(d, btn_text, url)

    def test_disabled_or_no_reply_topics(self):
        for text in ["free spin activation left?", "account register how"]:
            d = classify_community_message(text)
            self.assertNotEqual(d.action, "reply")
            self.assertIsNone(d.reply)

        for text in ["customer service contact", "I was removed from group", "are referral links allowed", "check my transaction history"]:
            d = classify_community_message(text)
            self.assertIn(d.action, {"admin_alert", "ignore"})
            self.assertIsNone(d.reply)

        d = classify_community_message("check transaction history now")
        self.assertEqual(d.action, "admin_alert")
        self.assertIsNone(d.reply)

    def test_mywin_hashtags_and_comeback(self):
        d = classify_community_message("what hashtags do I use for MyWin")
        self.assertEqual(d.intent, "mywin_hashtags")
        self.assertIn("#MyWin", d.reply)
        self.assertIn("#ComebackIsReal", d.reply)

        d2 = classify_community_message("my win over 50x", has_photo=True)
        self.assertEqual(d2.intent, "mywin_comeback_tag")
        self.assertIn("#ComebackIsReal", d2.reply)
        self.assertEqual(d2.emoji, "🔥")

    def test_fingerprint_and_normalization(self):
        self.assertIsNone(message_fingerprint(None))
        self.assertIsNone(message_fingerprint("   "))
        f1 = message_fingerprint("Code not working!!!")
        f2 = message_fingerprint("code not working 😭")
        self.assertEqual(f1, f2)

        n = normalize_for_fingerprint("Hey @abc check https://x.y/z voucher")
        self.assertNotIn("@abc", n)
        self.assertNotIn("http", n)

        d = classify_community_message("voucher not working")
        self.assertIsNotNone(d.fingerprint)

    def test_safety_phrases_not_in_replies(self):
        banned = ["guaranteed win", "sure win", "deposit now", "withdraw guaranteed", "bonus guaranteed"]
        samples = [
            "where to enter voucher code",
            "code not working",
            "how claim free spin",
            "new user how to start",
            "what hashtags do I use for mywin",
            "official channel",
        ]
        replies = [classify_community_message(s).reply or "" for s in samples]
        all_text = " ".join(replies).lower()
        for phrase in banned:
            self.assertNotIn(phrase, all_text)


if __name__ == "__main__":
    unittest.main()
