from aiogram.fsm.state import State, StatesGroup


class ApplicationStates(StatesGroup):
    waiting_for_reason = State()

