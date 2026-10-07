from aiogram.fsm.state import State, StatesGroup


class ApplicationStates(StatesGroup):
    waiting_for_reason = State()


class CreatorMessageStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_message = State()


class ThanksCommentStates(StatesGroup):
    waiting_for_comment = State()
