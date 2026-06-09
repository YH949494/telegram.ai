import os
import unittest
from unittest.mock import patch

from app.config import Settings


class SettingsEngagementChatIdsTests(unittest.TestCase):
    def _build_settings(self, engagement_target_chat_ids_raw: str):
        env = {
            "TELEGRAM_TOKEN": "token",
            "MONGODB_URI": "mongodb://localhost:27017",
            "ENGAGEMENT_TARGET_CHAT_IDS": engagement_target_chat_ids_raw,
        }
        with patch.dict(os.environ, env, clear=True):
            return Settings()

    def test_empty_string_returns_empty_list(self):
        settings = self._build_settings("")
        self.assertEqual(settings.engagement_target_chat_ids, [])

    def test_single_id_string(self):
        settings = self._build_settings("-1002304653063")
        self.assertEqual(settings.engagement_target_chat_ids, [-1002304653063])

    def test_comma_separated_ids(self):
        settings = self._build_settings("1,2,3")
        self.assertEqual(settings.engagement_target_chat_ids, [1, 2, 3])

    def test_whitespace_trimming(self):
        settings = self._build_settings(" 1,  2 ,   3  ")
        self.assertEqual(settings.engagement_target_chat_ids, [1, 2, 3])

    def test_invalid_integer_raises_value_error(self):
        settings = self._build_settings("1,abc,3")
        with self.assertRaises(ValueError):
            _ = settings.engagement_target_chat_ids

    def test_official_channel_cta_disabled_by_default(self):
        settings = self._build_settings("")
        self.assertFalse(settings.official_channel_cta_enabled)

    def test_official_channel_cta_can_be_enabled(self):
        env = {
            "TELEGRAM_TOKEN": "token",
            "MONGODB_URI": "mongodb://localhost:27017",
            "OFFICIAL_CHANNEL_CTA_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()
        self.assertTrue(settings.official_channel_cta_enabled)
