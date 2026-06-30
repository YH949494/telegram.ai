import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.error import BadRequest

from app.handlers import _delete_thai_language_message_if_needed


def make_message(*, text=None, caption=None, chat_type="group"):
    return SimpleNamespace(
        text=text,
        caption=caption,
        chat=SimpleNamespace(type=chat_type),
        chat_type=chat_type,
        chat_id=-100123,
        message_id=456,
        from_user=SimpleNamespace(id=789),
    )


def make_context(delete_side_effect=None):
    bot = SimpleNamespace(delete_message=AsyncMock(side_effect=delete_side_effect))
    return SimpleNamespace(bot=bot)


class ThaiLanguageDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = SimpleNamespace(thai_language_delete_enabled=True)
        self.settings_patch = patch("app.handlers.get_settings", return_value=self.settings)
        self.settings_patch.start()

    async def asyncTearDown(self):
        self.settings_patch.stop()

    async def test_thai_text_message_gets_deleted(self):
        context = make_context()
        deleted = await _delete_thai_language_message_if_needed(
            make_message(text="hello สวัสดี"),
            context,
        )

        self.assertTrue(deleted)
        context.bot.delete_message.assert_awaited_once_with(chat_id=-100123, message_id=456)

    async def test_thai_caption_gets_deleted(self):
        context = make_context()
        deleted = await _delete_thai_language_message_if_needed(
            make_message(caption="promo ภาษาไทย"),
            context,
        )

        self.assertTrue(deleted)
        context.bot.delete_message.assert_awaited_once_with(chat_id=-100123, message_id=456)

    async def test_english_message_is_not_deleted(self):
        context = make_context()
        deleted = await _delete_thai_language_message_if_needed(
            make_message(text="hello team"),
            context,
        )

        self.assertFalse(deleted)
        context.bot.delete_message.assert_not_awaited()

    async def test_private_thai_message_is_not_deleted(self):
        context = make_context()
        deleted = await _delete_thai_language_message_if_needed(
            make_message(text="สวัสดี", chat_type="private"),
            context,
        )

        self.assertFalse(deleted)
        context.bot.delete_message.assert_not_awaited()

    async def test_delete_failure_does_not_crash(self):
        context = make_context(delete_side_effect=BadRequest("message can't be deleted"))
        deleted = await _delete_thai_language_message_if_needed(
            make_message(text="สวัสดี"),
            context,
        )

        self.assertTrue(deleted)
        context.bot.delete_message.assert_awaited_once_with(chat_id=-100123, message_id=456)


if __name__ == "__main__":
    unittest.main()
