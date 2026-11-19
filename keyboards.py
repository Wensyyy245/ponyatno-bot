"""Клавиатуры «ПОНЯТНО».

Магазин разделён на три отдельных входа: запросы, подписка, поддержка.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import db


def _b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _url(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def main_menu(user) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("📸 Отправить домашку", "m:solve"))
    kb.row(_b("📝 Текстом", "m:text"), _b("✅ Проверить решение", "m:check"))
    kb.row(_b("🎓 Класс и предмет", "m:setup"), _b("📊 Профиль", "m:profile"))
    kb.row(_b("🛒 Купить запросы", "m:pay"), _b("🎁 Позвать друга", "m:ref"))
    kb.row(_b("❓ Как это работает", "m:help"))
    return kb.as_markup()


def back_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def back_shop() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("⬅️ В магазин", "m:pay"), _b("🏠 Меню", "m:menu"))
    return kb.as_markup()


def solve_prompt_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("🎲 Пример задачи", "m:demo"))
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def answer_kb(has_task: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("🤔 Не понял — проще", "a:simpler"), _b("🎯 Похожая задача", "a:similar"))
    if has_task:
        kb.row(_b("✅ Проверить моё решение", "a:check"))
    kb.row(_b("📸 Новая задача", "m:solve"), _b("📊 Профиль", "m:profile"))
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def grades_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.add(*[_b(f"{g} класс", f"gr:{g}") for g in config.GRADES])
    kb.adjust(4)
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def subjects_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label, emoji in config.SUBJECTS:
        kb.add(_b(f"{emoji} {label}", f"sub:{key}"))
    kb.adjust(2)
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def setup_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("🎓 Изменить класс", "m:grades"), _b("📚 Изменить предмет", "m:subjects"))
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


# --- магазин ---------------------------------------------------------------
def shop_kb(user) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("🎟 Купить запросы", "shop:req"))
    kb.row(_b("♾ Подписка — безлимит", "shop:sub"))
    kb.row(_b("💛 Поддержать администрацию", "shop:don"))
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def req_packs_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, (count, stars) in config.REQUEST_PACKS.items():
        kb.row(_b(f"{count} запросов — {stars} ⭐", f"buy:{key}"))
    kb.row(_b("⬅️ В магазин", "m:pay"), _b("🏠 Меню", "m:menu"))
    return kb.as_markup()


def sub_plans_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, (days, stars, title) in config.SUB_PLANS.items():
        kb.row(_b(f"{title} — {stars} ⭐", f"buy:{key}"))
    kb.row(_b("⬅️ В магазин", "m:pay"), _b("🏠 Меню", "m:menu"))
    return kb.as_markup()


def donate_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    packs = config.DONATION_PACKS
    kb.row(*[_b(f"{s} ⭐", f"don:{s}") for s in packs[:2]])
    kb.row(*[_b(f"{s} ⭐", f"don:{s}") for s in packs[2:]])
    kb.row(_b("💫 Своя сумма", "pay:custom"))
    kb.row(_b("⬅️ В магазин", "m:pay"), _b("🏠 Меню", "m:menu"))
    return kb.as_markup()


def after_pay_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("📸 Отправить домашку", "m:solve"))
    kb.row(_b("📊 Профиль", "m:profile"), _b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def limit_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("🎟 Купить запросы", "shop:req"))
    kb.row(_b("♾ Взять безлимит", "shop:sub"))
    kb.row(_b("🎁 Позвать друга (+5)", "m:ref"))
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


# --- рефералка -------------------------------------------------------------
def ref_kb(has_channel: bool, checked: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_channel:
        if config.CHANNEL_URL:
            kb.row(_url("📢 Подписаться на канал", config.CHANNEL_URL))
        kb.row(_b("✅ Я подписался — проверить", "ref:check"))
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()

def subscribe_kb() -> InlineKeyboardMarkup:
    """Обязательная подписка на канал перед использованием бота."""
    kb = InlineKeyboardBuilder()
    if config.CHANNEL_URL:
        kb.row(_url("📢 Подписаться на канал", config.CHANNEL_URL))
    kb.row(_b("✅ Я подписался — проверить", "gate:check"))
    return kb.as_markup()
# --- админ-панель ----------------------------------------------------------
def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("📊 Статистика", "adm:stats"))
    kb.row(_b("👤 Пользователь", "adm:user"), _b("🎁 Выдать", "adm:grant"))
    kb.row(_b("💸 Скидки", "adm:disc"), _b("📢 Рассылка", "adm:cast"))
    kb.row(_b("🧾 Платежи", "adm:pay"), _b("⚙️ Диагностика", "adm:diag"))
    kb.row(_b("⬅️ В меню", "m:menu"))
    return kb.as_markup()


def admin_back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("⬅️ В админку", "adm:menu"))
    return kb.as_markup()


def admin_user_kb(user_id: int, banned: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("+10 запросов", f"adm:give:req:10:{user_id}"),
           _b("+50 запросов", f"adm:give:req:50:{user_id}"))
    kb.row(_b("+30 дней подписки", f"adm:give:sub:30:{user_id}"),
           _b("+90 дней", f"adm:give:sub:90:{user_id}"))
    kb.row(_b("Разбанить" if banned else "Забанить", f"adm:ban:{user_id}"))
    kb.row(_b("⬅️ В админку", "adm:menu"))
    return kb.as_markup()


def admin_discount_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("−10% на сутки", "adm:disc:new:10:24"))
    kb.row(_b("−20% на сутки", "adm:disc:new:20:24"))
    kb.row(_b("−30% на 3 дня", "adm:disc:new:30:72"))
    kb.row(_b("✍️ Свой процент и срок", "adm:disc:custom"))
    kb.row(_b("🧹 Отключить все скидки", "adm:disc:clear"))
    kb.row(_b("⬅️ В админку", "adm:menu"))
    return kb.as_markup()


def admin_cast_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(_b("✅ Отправить всем", "adm:cast:go"))
    kb.row(_b("❌ Отмена", "adm:menu"))
    return kb.as_markup()