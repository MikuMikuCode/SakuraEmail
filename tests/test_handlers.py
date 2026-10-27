import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import _cancel_current_action


class CancelActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_clears_current_date_input_and_removes_button(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            message_id=202,
            edit_reply_markup=AsyncMock(),
        )
        callback = SimpleNamespace(message=message, answer=AsyncMock())
        state = AsyncMock()
        state.get_data.return_value = {
            "action_prompt_chat_id": 101,
            "action_prompt_message_id": 202,
        }
        state.get_state.return_value = "WorkReportStates:waiting_for_date"

        await _cancel_current_action(callback, state)

        state.clear.assert_awaited_once_with()
        callback.answer.assert_awaited_once_with("Действие отменено")
        message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


if __name__ == "__main__":
    unittest.main()
