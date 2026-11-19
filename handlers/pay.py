"""Магазин «ПОНЯТНО»: три отдельных товара — запросы, подписка, поддержка.

Все платежи — Telegram Stars (XTR), без автосписаний и без карт.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

import config
import db
import discounts
import keyboards as kb
import states
from handlers.common import ensure, safe_edit

router = Router(name="pay")
log = logging.getLogger(__name__)


def _access_line(user) -> str:
    if db.is_pro(user):
        return f"♾ Безлимит активен · осталось {db.pro_days_left(user)} дн."
    return (f"🎟 Бесплатных сегодня: {db.daily_free_left(user)} из {config.FREE_SOLVES_PER_DAY}\n"
            f"📦 Купленных запросов: {db.requests_left(user)}")


def shop_text(user) -> str:
    percent, until = discounts.current()
    sale = (f"\n🔥 Скидка −{percent}% до {until.replace('T', ' ')[:16]}\n" if percent else "")
    return (
        "<b>Магазин</b>\n\n"
        f"{_access_line(user)}\n"
        f"{sale}\n"
        "Выбери, что нужно:\n\n"
        "<b>🎟 Запросы</b> — штучные разборы, не сгорают и не тратятся по времени.\n\n"
        "<b>♾ Подписка</b> — безлимит на срок: можно разбирать всю домашку подряд.\n\n"
        "<b>💛 Поддержать</b> — просто спасибо проекту, без доступа и обязательств."
    )


def req_text() -> str:
    rows = "\n".join(f"• {n} запросов — <b>{discounts.label(s)}</b>" for n, s in config.REQUEST_PACKS.values())
    return (
        "<b>Запросы</b>\n\n"
        f"{rows}\n\n"
        "<b>Как это работает</b>\n"
        "1. Сначала списываются бесплатные дневные\n"
        "2. Потом купленные — они не сгорают и ждут, пока понадобятся\n"
        "3. Один запрос = один разбор (фото или текст)\n\n"
        "<i>Оплата звёздами Telegram, карта не нужна.</i>"
    )


def sub_text(user) -> str:
    rows = "\n".join(f"• {title} — <b>{discounts.label(s)}</b>" for _, s, title in config.SUB_PLANS.values())
    tail = (f"\n\n♾ У тебя уже активна подписка: осталось {db.pro_days_left(user)} дн."
            if db.is_pro(user) else "")
    return (
        "<b>Подписка — безлимит</b>\n\n"
        f"{rows}\n\n"
        "<b>Что даёт</b>\n"
        "• не считаются запросы вообще: ни бесплатные, ни купленные\n"
        "• можно разбирать подряд всю домашку\n"
        "• идеально перед контрольной и в конце четверти\n\n"
        "<i>Подписка не продлевается сама — по окончании просто станет как было, "
        "без списаний.</i>"
        f"{tail}"
    )


def don_text() -> str:
    packs = " · ".join(f"{s} ⭐" for s in config.DONATION_PACKS)
    return (
        "<b>Поддержать администрацию</b>\n\n"
        "Это не покупка доступа, а просто помощь проекту: сервер, AI-разборы, "
        "новые предметы. Если нужны запросы — лучше взять пакет или подписку.\n\n"
        f"{packs} или своя сумма\n\n"
        "<i>Спасибо. Правда.</i>"
    )


# --- экраны ----------------------------------------------------------------
@router.callback_query(F.data == "m:pay")
async def cb_shop(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    user = ensure(cb.from_user)
    await safe_edit(cb.message, shop_text(user), kb.shop_kb(user))


@router.callback_query(F.data == "shop:req")
async def cb_req(cb: CallbackQuery) -> None:
    await cb.answer()
    ensure(cb.from_user)
    await safe_edit(cb.message, req_text(), kb.req_packs_kb())


@router.callback_query(F.data == "shop:sub")
async def cb_sub(cb: CallbackQuery) -> None:
    await cb.answer()
    user = ensure(cb.from_user)
    await safe_edit(cb.message, sub_text(user), kb.sub_plans_kb())


@router.callback_query(F.data == "shop:don")
async def cb_don(cb: CallbackQuery) -> None:
    await cb.answer()
    ensure(cb.from_user)
    await safe_edit(cb.message, don_text(), kb.donate_kb())


# --- счета -----------------------------------------------------------------
async def _invoice(cb: CallbackQuery, title: str, description: str,
                   payload: str, stars: int) -> None:
    await cb.bot.send_invoice(
        chat_id=cb.from_user.id,
        title=title,
        description=description,
        payload=payload,
        currency=config.CURRENCY,
        prices=[LabeledPrice(label=title, amount=stars)],
    )


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(cb: CallbackQuery) -> None:
    ensure(cb.from_user)
    key = cb.data.split(":", 1)[1]
    uid = cb.from_user.id

    if key in config.REQUEST_PACKS:
        count, base = config.REQUEST_PACKS[key]
        stars = discounts.price(base)[0]
        await cb.answer()
        await _invoice(cb, f"{count} запросов", f"Пакет на {count} разборов. Не сгорают.",
                       f"req:{uid}:{key}", stars)
        return

    if key in config.SUB_PLANS:
        days, base, title = config.SUB_PLANS[key]
        stars = discounts.price(base)[0]
        await cb.answer()
        await _invoice(cb, title, f"Безлимит разборов на {days} дней.",
                       f"sub:{uid}:{key}", stars)
        return

    await cb.answer("Такого товара нет", show_alert=True)


@router.callback_query(F.data.startswith("don:"))
async def cb_donate(cb: CallbackQuery) -> None:
    ensure(cb.from_user)
    raw = cb.data.split(":", 1)[1]
    if not raw.isdigit() or int(raw) not in config.DONATION_PACKS:
        await cb.answer("Пакет не найден", show_alert=True)
        return
    stars = int(raw)
    await cb.answer()
    await _invoice(cb, f"Поддержка · {stars} ⭐", "Спасибо за помощь проекту.",
                   f"don:{cb.from_user.id}:{stars}", stars)


@router.callback_query(F.data == "pay:custom")
async def cb_custom(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    ensure(cb.from_user)
    await state.set_state(states.Donate.amount)
    await safe_edit(
        cb.message,
        "<b>Своя сумма</b>\n\n"
        f"Напиши число звёзд от {config.CUSTOM_DONATE_MIN} до {config.CUSTOM_DONATE_MAX}.\n"
        "<i>Например: 30</i>",
        kb.back_shop(),
    )


@router.message(states.Donate.amount)
async def on_custom_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(" ", "")
    if not raw.isdigit():
        await message.answer("Нужно целое число звёзд. Например: 30")
        return
    stars = int(raw)
    if not config.CUSTOM_DONATE_MIN <= stars <= config.CUSTOM_DONATE_MAX:
        await message.answer(f"Сумма от {config.CUSTOM_DONATE_MIN} до {config.CUSTOM_DONATE_MAX} ⭐.")
        return
    await state.clear()
    ensure(message.from_user)
    await message.bot.send_invoice(
        chat_id=message.from_user.id,
        title=f"Поддержка · {stars} ⭐",
        description="Спасибо за помощь проекту.",
        payload=f"don:{message.from_user.id}:{stars}",
        currency=config.CURRENCY,
        prices=[LabeledPrice(label="Донат", amount=stars)],
    )


# --- платёжные события -----------------------------------------------------
def _expected_stars(kind: str, key: str) -> int | None:
    if kind == "req" and key in config.REQUEST_PACKS:
        return discounts.price(config.REQUEST_PACKS[key][1])[0]
    if kind == "sub" and key in config.SUB_PLANS:
        return discounts.price(config.SUB_PLANS[key][1])[0]
    if kind == "don" and key.isdigit():
        return int(key)
    return None


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    try:
        parts = (query.invoice_payload or "").split(":")
        ok = False
        if query.currency == config.CURRENCY and len(parts) == 3:
            kind, uid, key = parts
            ok = (uid == str(query.from_user.id)
                  and _expected_stars(kind, key) == query.total_amount)
        await query.answer(ok=ok, error_message=None if ok else "Счёт устарел. Открой магазин заново.")
    except Exception:  # noqa: BLE001
        log.exception("pre_checkout_query")
        try:
            await query.answer(ok=False, error_message="Ошибка оплаты, попробуй ещё раз.")
        except Exception:  # noqa: BLE001
            pass


@router.message(F.successful_payment)
async def on_paid(message: Message) -> None:
    sp = message.successful_payment
    uid = message.from_user.id
    ensure(message.from_user)

    if sp.currency != config.CURRENCY:
        log.warning("Чужая валюта платежа: %s", sp.currency)
        return

    charge = sp.telegram_payment_charge_id or ""
    if charge and db.has_charge(charge):
        await message.answer("Этот платёж уже учтён 👍")
        return

    parts = (sp.invoice_payload or "").split(":")
    if len(parts) != 3 or parts[1] != str(uid):
        log.warning("Неизвестный payload: %s", sp.invoice_payload)
        await message.answer("Платёж получен, но не распознан. Напиши в поддержку.")
        return

    kind, _, key = parts

    if kind == "req" and key in config.REQUEST_PACKS:
        count, stars = config.REQUEST_PACKS[key]
        db.add_payment(uid, sp.invoice_payload, "requests", sp.total_amount, charge)
        total = db.add_requests(uid, count)
        await message.answer(
            f"🎟 <b>Начислено {count} запросов</b>\n\n"
            f"Теперь у тебя <b>{total}</b> купленных. Они не сгорают.\n"
            "Бесплатные дневные по-прежнему начисляются каждый день.",
            reply_markup=kb.after_pay_kb(),
        )
        log.info("Покупка %s запросов: %s", count, uid)
        return

    if kind == "sub" and key in config.SUB_PLANS:
        days, stars, title = config.SUB_PLANS[key]
        db.add_payment(uid, sp.invoice_payload, "subscription", sp.total_amount, charge)
        db.grant_subscription(uid, days)
        user = db.get_user(uid)
        left = db.pro_days_left(user) if user else days
        await message.answer(
            "♾ <b>Безлимит подключён</b>\n\n"
            f"Тариф: {title}\n"
            f"Осталось: <b>{left}</b> дн.\n\n"
            "Присылай задания подряд — запросы не считаются.",
            reply_markup=kb.after_pay_kb(),
        )
        log.info("Подписка %s: %s", key, uid)
        return

    if kind == "don" and key.isdigit():
        stars = int(key)
        db.add_payment(uid, sp.invoice_payload, "donate", sp.total_amount, charge)
        total = db.add_donation(uid, stars)
        await message.answer(
            f"💛 Спасибо. <b>{stars} ⭐</b> ушли в проект.\n"
            f"Всего от тебя: <b>{total}</b> ⭐",
            reply_markup=kb.after_pay_kb(),
        )
        log.info("Донат %s ⭐ от %s", stars, uid)
        return

    log.warning("Неизвестный товар: %s", sp.invoice_payload)
    await message.answer("Платёж получен, но товар не распознан. Напиши в поддержку.")
