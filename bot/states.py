from aiogram.fsm.state import State, StatesGroup


class ApplicationStates(StatesGroup):
    waiting_for_reason = State()


class CreatorMessageStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_message = State()


class CreatorBroadcastStates(StatesGroup):
    waiting_for_message = State()
    confirming = State()
    sending = State()


class ThanksCommentStates(StatesGroup):
    waiting_for_comment = State()


class WorkReportStates(StatesGroup):
    choosing_date = State()
    waiting_for_date = State()
    reviewing_existing = State()
    waiting_for_report = State()
    confirming = State()


class WorkScheduleStates(StatesGroup):
    waiting_for_schedule = State()
