import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app import db as db_module
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

        d2 = classify_community_message("do I need #ComebackIsReal if my win over 50x", has_photo=True)
        self.assertEqual(d2.intent, "mywin_comeback_tag")
        self.assertIn("#ComebackIsReal", d2.reply)
        self.assertEqual(d2.emoji, "🔥")


    def test_campaign_hashtag_signals_no_reply(self):
        samples = [
            "#ComebackIsReal",
            "#ComebacklsReal",
            "ComebacklsReal",
            "comeback is real",
            "#MYWIN",
            "#mywin",
            "#claimcode",
            "AdvantPaly Gold,✅",
            "AdvantPlay Gold ✅",
            "\"AdvantPlay Gold ✅\" 🥇",
            "#MyWin\nAdvantPlay Gold ✅",
            "VIP advantplay win” + share result 👑",
            "Silver spin secured #ComebackIsReal",
            "#MYWIN Silver spin secured #ComebackIsReal",
            "Bronze locked 🔥 AdvantPlay",
        ]
        for text in samples:
            d = classify_community_message(text)
            self.assertEqual(d.intent, "campaign_hashtag_signal")
            self.assertEqual(d.action, "ignore")
            self.assertIsNone(d.reply)
            self.assertFalse(d.admin_alert)

    def test_real_mywin_questions_still_reply(self):
        d1 = classify_community_message("what hashtags do I use for MyWin")
        self.assertEqual(d1.intent, "mywin_hashtags")
        self.assertEqual(d1.action, "reply")

        d2 = classify_community_message("how do I submit my spin result in MyWin")
        self.assertEqual(d2.intent, "mywin_submit_how")
        self.assertEqual(d2.action, "reply")

        d3 = classify_community_message("if win over 50x what tag should I use")
        self.assertIn(d3.intent, {"mywin_comeback_tag", "mywin_hashtags"})
        self.assertEqual(d3.action, "reply")

    def test_external_link_spam_and_allowlist(self):
        spam = classify_community_message("https://app.jazz55.io/aff/74Kj")
        self.assertEqual(spam.intent, "external_link_or_affiliate_spam")
        self.assertTrue(spam.admin_alert)
        self.assertIsNone(spam.reply)

        official = classify_community_message("https://t.me/advantplayofficial/714")
        self.assertNotEqual(official.intent, "external_link_or_affiliate_spam")

    def test_job_spam_no_reply(self):
        d1 = classify_community_message("Ищу маленькую команду людей, которые могут помочь с выполнением задач на скла")
        self.assertEqual(d1.intent, "job_or_task_spam")
        self.assertEqual(d1.action, "ignore")
        self.assertIsNone(d1.reply)

        d2 = classify_community_message("part time job task team")
        self.assertEqual(d2.intent, "job_or_task_spam")
        self.assertEqual(d2.action, "ignore")

    def test_obfuscated_promo_spam_admin_alert_no_reply(self):
        spam = classify_community_message("💲 5️⃣0️⃣ 🅰️🅰️🅰️🅰️ 🌟 🅰️🅰️🅰️🅰️ ... Stаrt and rеcеivе yоur gi...")
        self.assertEqual(spam.intent, "obfuscated_promo_spam")
        self.assertEqual(spam.category, "spam_or_abuse")
        self.assertEqual(spam.action, "admin_alert")
        self.assertTrue(spam.admin_alert)
        self.assertTrue(spam.sensitive)
        self.assertIsNone(spam.reply)
        self.assertGreaterEqual(spam.confidence, 0.8)

    def test_short_normal_chat_remains_unknown(self):
        d = classify_community_message("Kuy")
        self.assertEqual(d.category, "unknown")
        self.assertEqual(d.action, "ignore")
        self.assertIsNone(d.intent)

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


    def test_duplicate_aggregation_sorts_by_latest_created_at(self):
        captured = []

        class FakeCollection:
            def aggregate(self, pipeline):
                captured.append(pipeline)
                return []

            def find(self, *args, **kwargs):
                return []

        class FakeDB(dict):
            def __getitem__(self, key):
                return FakeCollection()

        with patch("app.db.get_db", return_value=FakeDB()):
            db_module.aggregate_community_helper_events(since=datetime.now(timezone.utc))

        duplicate_pipeline = next(p for p in captured if any(stage.get("$match", {}).get("fingerprint") == {"$ne": None} for stage in p))
        self.assertEqual(duplicate_pipeline[1], {"$sort": {"created_at": -1}})


if __name__ == "__main__":
    unittest.main()
