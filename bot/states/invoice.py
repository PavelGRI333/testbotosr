from aiogram.fsm.state import State, StatesGroup


class InvoiceEdit(StatesGroup):
    overview = State()
    waiting_value = State()
