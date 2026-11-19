"""Админ-панель: статистика, выдача, скидки, рассылка, платежи, диагностика.

Здесь же живёт публичная кнопка проверки подписки (gate:check) — она должна быть
зарегистрирована раньше общего перехватчика кнопок, иначе он её съедает.
"""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import ai
import config
import db
import discounts
import keyboards as kb
import states
from handlers.common import ensure, grant_ref_bonus, safe_edit, subscribed

router = Router(name="gate")
admin_router = Router(name="admin")
log = logging.getLogger("admin")


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        return bool(event.from_user) and event.from_user.id in config.ADMIN_IDS


admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())


# --- публичная проверка подписки -------------------------------------------
@router.callback_query(F.data == "gate:check")
async def cb_gate_check(cb: CallbackQuery, state: FSMContext) -> None:
    result = await subscribed(cb.bot, cb.from_user.id, force=True)
    if result is False:
        await cb.answer("Пока не вижу подписку. Подпишись и нажми ещё раз.", show_alert=True)
        return
    if result is None:
        await cb.answer("Не могу проверить подписку — напиши в поддержку.", show_alert=True)
        return
    await state.clear()
    user = ensure(cb.from_user)
    await grant_ref_bonus(cb.bot, cb.from_user.id)
    await cb.answer("Готово, доступ открыт")
    await safe_edit(cb.message, "Доступ открыт. Пришли задание — фото или текстом.",
                    kb.main_menu(user))


# --- вход -------------------------------------------------------------------
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(panel_text(), reply_markup=kb.admin_menu())


def panel_text() -> str:
    st = db.admin_stats()
    disc = discounts.current()
    disc_line = (f"−{disc[0]}% до {disc[1].replace('T', ' ')[:16]}" if disc[0]
                 else "нет активной скидки")
    return (
        "<b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{st.get('users', 0)}</b> · новых сегодня {st.get('new_today', 0)}\n"
        f"⚡ Активных сегодня: {st.get('active_today', 0)}\n"
        f"📚 Разборов: {st.get('solves_today', 0)} за сегодня · {st.get('solves_total', 0)} всего\n"
        f"💫 Звёзд получено: {st.get('stars', 0)} ({st.get('payments', 0)} платежей)\n"
        f"♾ Подписок: {st.get('pro', 0)} · 🎟 Запросов на руках: {st.get('requests_pool', 0)}\n"
        f"🤖 AI-вызовов сегодня: {st.get('ai_today', 0)} из {st.get('ai_limit', 0)}\n"
        f"💸 Скидка: {disc_line}"
    )


@admin_router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await safe_edit(cb.message, panel_text(), kb.admin_menu())


# --- статистика -------------------------------------------------------------
@admin_router.callback_query(F.data == "adm:stats")
async def cb_stats(cb: CallbackQuery) -> None:
    await cb.answer()
    st = db.admin_stats()
    top = db.q("SELECT first_name, username, solves_total FROM users "
               "WHERE solves_total > 0 ORDER BY solves_total DESC LIMIT 5")
    top_lines = "\n".join(
        f"{i}. {html.escape(r['first_name'] or '—')}"
        + (f" (@{html.escape(r['username'])})" if r["username"] else "")
        + f" — {r['solves_total']}"
        for i, r in enumerate(top, 1)
    ) or "пока пусто"
    text = (
        "<b>Статистика</b>\n\n"
        f"👥 Всего: <b>{st.get('users', 0)}</b>\n"
        f"🆕 Новых сегодня: {st.get('new_today', 0)}\n"
        f"⚡ Заходили сегодня: {st.get('active_today', 0)}\n"
        f"🚫 Забанено: {st.get('banned', 0)}\n"
        f"🎁 Пришли по ссылке: {st.get('refs', 0)}\n\n"
        f"📚 Разборов сегодня: {st.get('solves_today', 0)}\n"
        f"📚 Разборов всего: {st.get('solves_total', 0)}\n"
        f"🗃 В кэше ответов: {st.get('cache', 0)}\n\n"
        f"🤖 AI сегодня: {st.get('ai_today', 0)} / {st.get('ai_limit', 0)}\n"
        f"💫 Звёзд: {st.get('stars', 0)} · платежей: {st.get('payments', 0)}\n"
        f"♾ Подписок: {st.get('pro', 0)}\n"
        f"🎟 Запросов у людей: {st.get('requests_pool', 0)}\n\n"
        f"<b>Кто больше всех решает</b>\n{top_lines}"
    )
    await safe_edit(cb.message, text, kb.admin_back())


# --- пользователь -----------------------------------------------------------
@admin_router.callback_query(F.data == "adm:user")
async def cb_user_ask(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(states.Admin.user_query)
    await safe_edit(cb.message,
                    "<b>Кто нужен?</b>\n\nПришли ID или @username.\n"
                    "<i>Например: 1053136340 или @kosta</i>",
                    kb.admin_back())


@admin_router.callback_query(F.data == "adm:grant")
async def cb_grant_ask(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(states.Admin.grant)
    await safe_edit(cb.message,
                    "<b>Кому выдать?</b>\n\nПришли ID или @username — открою карточку, "
                    "где можно выдать запросы или подписку.",
                    kb.admin_back())


async def _show_user(target: Message, user_row) -> None:
    u = user_row
    sub = (f"♾ до {db.iso(db.now())[:10]} +{db.pro_days_left(u)} дн."
           if db.is_pro(u) else "нет")
    text = (
        f"<b>Пользователь {u['user_id']}</b>\n\n"
        f"Имя: {html.escape(u['first_name'] or '—')}"
        + (f" · @{html.escape(u['username'])}" if u["username"] else "") + "\n"
        f"Класс: {u['grade']} · предмет: {u['subject']}\n"
        f"Создан: {u['created_at'][:16].replace('T', ' ')}\n\n"
        f"♾ Подписка: {sub}\n"
        f"🎟 Купленных запросов: <b>{db.requests_left(u)}</b>\n"
        f"🎁 Сегодня бесплатных: {db.daily_free_left(u)} из {config.FREE_SOLVES_PER_DAY}\n"
        f"📚 Разборов: {u['solves_total']} (XP {u['xp']}, серия {u['streak']})\n"
        f"💫 Донаты: {u['donated']} ⭐\n"
        f"🚫 Бан: {'да' if db.is_banned(u) else 'нет'}\n"
        f"🔗 Рефов: {db.count_refs(u['user_id'])}"
    )
    await target.answer(text, reply_markup=kb.admin_user_kb(u["user_id"], db.is_banned(u)))


@admin_router.message(states.Admin.user_query)
async def on_user_query(message: Message, state: FSMContext) -> None:
    row = db.find_user(message.text or "")
    if row is None:
        await message.answer("Не нашёл такого. Пришли числовой ID или @username.")
        return
    await state.clear()
    await _show_user(message, row)


@admin_router.message(states.Admin.grant)
async def on_grant_query(message: Message, state: FSMContext) -> None:
    row = db.find_user(message.text or "")
    if row is None:
        await message.answer("Не нашёл такого. Пришли числовой ID или @username.")
        return
    await state.clear()
    await _show_user(message, row)


@admin_router.callback_query(F.data.startswith("adm:give:"))
async def cb_give(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    # adm:give:req:<n>:<uid> | adm:give:sub:<days>:<uid>
    if len(parts) != 5:
        await cb.answer("Кривая команда", show_alert=True)
        return
    _, _, kind, amount, uid = parts
    uid, amount = int(uid), int(amount)
    if db.get_user(uid) is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    if kind == "req":
        total = db.add_requests(uid, amount)
        await cb.answer(f"Начислено {amount}. Баланс: {total}", show_alert=True)
        try:
            await cb.bot.send_message(uid, f"🎁 Тебе начислили <b>{amount} запросов</b>. "
                                           f"Всего: <b>{total}</b>.")
        except Exception:  # noqa: BLE001
            log.info("не смог уведомить %s", uid)
    elif kind == "sub":
        db.grant_subscription(uid, amount)
        left = db.pro_days_left(db.get_user(uid))
        await cb.answer(f"Подписка продлена на {amount} дн.", show_alert=True)
        try:
            await cb.bot.send_message(uid, f"♾ Тебе включили безлимит на <b>{amount} дней</b>. "
                                           f"Осталось: {left} дн.")
        except Exception:  # noqa: BLE001
            log.info("не смог уведомить %s", uid)
    else:
        await cb.answer("Неизвестный тип", show_alert=True)
        return
    await _show_user(cb.message, db.get_user(uid))


@admin_router.callback_query(F.data.startswith("adm:ban:"))
async def cb_ban(cb: CallbackQuery) -> None:
    uid = int(cb.data.split(":")[2])
    row = db.get_user(uid)
    if row is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    new_state = not db.is_banned(row)
    db.set_banned(uid, new_state)
    await cb.answer("Забанен" if new_state else "Разбанен")
    await _show_user(cb.message, db.get_user(uid))


# --- скидки -----------------------------------------------------------------
@admin_router.callback_query(F.data == "adm:disc")
async def cb_disc(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await safe_edit(cb.message, disc_text(), kb.admin_discount_kb())


def disc_text() -> str:
    percent, until = discounts.current()
    rows = db.discounts_list()
    active = (f"−{percent}% действует до {until.replace('T', ' ')[:16]}" if percent
              else "сейчас скидки нет")
    history = []
    for r in rows[:6]:
        mark = "✅" if r["until"] > db.iso(db.now()) else "⌛"
        history.append(f"{mark} −{r['percent']}% до {r['until'].replace('T', ' ')[:16]}")
    hist = "\n".join(history) or "пока не создавали"
    return (
        "<b>Скидки</b>\n\n"
        f"{active}\n\n"
        "<i>Скидка применяется к пакетам запросов и к подписке. "
        "Донат не скидывается.</i>\n\n"
        f"<b>История</b>\n{hist}"
    )


@admin_router.callback_query(F.data.startswith("adm:disc:new:"))
async def cb_disc_new(cb: CallbackQuery) -> None:
    _, _, _, percent, hours = cb.data.split(":")
    db.add_discount(int(percent), float(hours))
    await cb.answer(f"Скидка −{percent}% включена")
    await safe_edit(cb.message, disc_text(), kb.admin_discount_kb())


@admin_router.callback_query(F.data == "adm:disc:clear")
async def cb_disc_clear(cb: CallbackQuery) -> None:
    count = db.clear_discounts()
    await cb.answer(f"Отключено скидок: {count}")
    await safe_edit(cb.message, disc_text(), kb.admin_discount_kb())


@admin_router.callback_query(F.data == "adm:disc:custom")
async def cb_disc_custom(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(states.Admin.discount_percent)
    await safe_edit(cb.message, "<b>Свой процент</b>\n\nНапиши число от 1 до 90.\n"
                                "<i>Например: 25</i>", kb.admin_back())


@admin_router.message(states.Admin.discount_percent)
async def on_disc_percent(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace("%", "")
    if not raw.isdigit() or not 1 <= int(raw) <= 90:
        await message.answer("Нужно число от 1 до 90.")
        return
    await state.update_data(percent=int(raw))
    await state.set_state(states.Admin.discount_hours)
    await message.answer("Теперь на сколько часов? <i>Например: 24</i>")


@admin_router.message(states.Admin.discount_hours)
async def on_disc_hours(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        hours = float(raw.replace(",", "."))
    except ValueError:
        await message.answer("Нужно число часов, например 24.")
        return
    if not 0.5 <= hours <= 24 * 90:
        await message.answer("Срок — от 0,5 до 2160 часов.")
        return
    data = await state.get_data()
    percent = int(data.get("percent", 10))
    await state.clear()
    db.add_discount(percent, hours)
    await message.answer(disc_text(), reply_markup=kb.admin_discount_kb())


# --- рассылка ---------------------------------------------------------------
@admin_router.callback_query(F.data == "adm:cast")
async def cb_cast(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(states.Admin.cast_text)
    users = len(db.all_user_ids())
    await safe_edit(cb.message,
                    f"<b>Рассылка</b>\n\nПришли текст сообщения (HTML можно).\n"
                    f"Получателей: <b>{users}</b>.\n\n"
                    "<i>Перед отправкой покажу превью и попрошу подтверждение.</i>",
                    kb.admin_back())


@admin_router.message(states.Admin.cast_text)
async def on_cast_text(message: Message, state: FSMContext) -> None:
    text = (message.html_text or message.text or "").strip()
    if len(text) < 3:
        await message.answer("Слишком коротко. Напиши текст рассылки.")
        return
    await state.update_data(cast=text[:3800])
    await state.set_state(states.Admin.cast_confirm)
    await message.answer(
        f"<b>Превью</b>\n\n{text[:3800]}\n\n———\n"
        f"Отправить <b>{len(db.all_user_ids())}</b> пользователям?",
        reply_markup=kb.admin_cast_kb(),
    )


@admin_router.callback_query(F.data == "adm:cast:go")
async def cb_cast_go(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("cast")
    await state.clear()
    if not text:
        await cb.answer("Текст потерялся, начни заново", show_alert=True)
        return
    await cb.answer("Отправляю…")
    ids = db.all_user_ids()
    ok = fail = 0
    progress = await cb.message.answer(f"Рассылка: 0 из {len(ids)}…")
    for i, uid in enumerate(ids, 1):
        try:
            await cb.bot.send_message(uid, text)
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
        if i % 25 == 0:
            try:
                await progress.edit_text(f"Рассылка: {i} из {len(ids)}… (ок {ok}, ошибок {fail})")
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.05)
    report = f"<b>Рассылка завершена</b>\n\nДоставлено: <b>{ok}</b>\nОшибок: {fail}"
    try:
        await progress.edit_text(report, reply_markup=kb.admin_menu())
    except Exception:  # noqa: BLE001 — сообщение могло не создаться
        await cb.message.answer(report, reply_markup=kb.admin_menu())
    log.info("рассылка: ok=%s fail=%s", ok, fail)


# --- платежи и диагностика --------------------------------------------------
@admin_router.callback_query(F.data == "adm:pay")
async def cb_payments(cb: CallbackQuery) -> None:
    await cb.answer()
    rows = db.recent_payments(10)
    kinds = {"requests": "запросы", "subscription": "подписка", "donate": "донат"}
    lines = [f"{r['created_at'][:16].replace('T', ' ')} · {kinds.get(r['kind'], r['kind'])} · "
             f"{r['stars']} ⭐ · {r['user_id']}" for r in rows] or ["платежей пока нет"]
    await safe_edit(cb.message, "<b>Последние платежи</b>\n\n" + "\n".join(lines),
                    kb.admin_back())


@admin_router.callback_query(F.data == "adm:diag")
async def cb_diag(cb: CallbackQuery) -> None:
    await cb.answer()
    st = ai.status()
    text = (
        "<b>Диагностика</b>\n\n"
        f"AI: <b>{st['state']}</b> — {html.escape(str(st['text'])[:120])}\n"
        f"Ключи: {ai.POOL.report()}\n"
        f"Модель: {config.AI_MODEL}\n"
        f"Вызовов AI сегодня: {db.ai_calls_today()} / {config.AI_DAILY_CALL_LIMIT}\n"
        f"Кэш ответов: {db.admin_stats().get('cache', 0)} записей\n"
        f"База: {config.DB_PATH}\n"
        f"Канал: {config.CHANNEL_ID or '—'} · обязательная подписка: "
        f"{'да' if config.REQUIRE_SUBSCRIPTION else 'нет'}\n"
        f"Админы: {', '.join(map(str, config.ADMIN_IDS)) or '—'}"
    )
    await safe_edit(cb.message, text, kb.admin_back())
