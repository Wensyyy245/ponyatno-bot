"""Состояния FSM."""
from aiogram.fsm.state import State, StatesGroup


class Task(StatesGroup):
    photo = State()
    text = State()
    check_task = State()
    check_answer = State()
    feedback = State()


class Donate(StatesGroup):
    amount = State()


class Admin(StatesGroup):
    user_query = State()
    grant = State()
    discount_percent = State()
    discount_hours = State()
    cast_text = State()
    cast_confirm = State()