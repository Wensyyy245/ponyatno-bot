"""Общие хендлеры «ПОНЯТНО»: старт, меню, профиль, настройки, рефералка."""
from __future__ import annotations

import html
import logging
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import ai
import config
import db
import keyboards as kb
import states
import ui

router = Router(name="common")
log = logging.getLogger(__name__)


async def safe_edit(message: Message, text: str, markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001 — сообщение старое, нет текста или текст не изменился
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


def ensure(from_user) -> db.sqlite3.Row:
    db.ensure_user(from_user.id, from_user.username, from_user.first_name)
    db.touch(from_user.id)
    return db.get_user(from_user.id)  # type: ignore[return-value]


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    ref_id = None
    args = (command.args or "").strip()
    if args.lower().startswith("ref_"):
        ref = db.get_by_ref(args[4:].strip().upper())
        if ref and ref["user_id"] != message.from_user.id:
            ref_id = ref["user_id"]

    is_new = db.get_user(message.from_user.id) is None
    db.ensure_user(message.from_user.id, message.from_user.username,
                   message.from_user.first_name, ref_id)
    db.touch(message.from_user.id)
    user = db.get_user(message.from_user.id)

    text = ui.welcome(message.from_user.first_name or "друг", user, ai.ready())
    keyboard = kb.main_menu(user)
    if is_new and ref_id:
        if config.CHANNEL_ID:
            text += ("\n\n🎁 Ты зашёл по ссылке друга. Подпишись на наш канал — "
                     f"и ему начислят <b>+{config.REF_REWARD_REQUESTS} запросов</b>.")
            keyboard = kb.ref_kb(True)
        else:
            granted = await grant_ref_bonus(message.bot, message.from_user.id)
            if granted:
                text += (f"\n\n🎁 Ты зашёл по ссылке друга: ему начислено "
                         f"<b>+{config.REF_REWARD_REQUESTS} запросов</b>.")
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


@router.message(Command("menu", "help"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = ensure(message.from_user)
    await message.answer(f"<b>{config.BRAND}</b> · меню\n\n<i>{ui.limits_line(user)}</i>",
                         reply_markup=kb.main_menu(user))


@router.callback_query(F.data == "m:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    user = ensure(cb.from_user)
    await safe_edit(cb.message, f"<b>{config.BRAND}</b> · меню\n\n<i>{ui.limits_line(user)}</i>",
                    kb.main_menu(user))


@router.callback_query(F.data == "m:profile")
async def cb_profile(cb: CallbackQuery) -> None:
    await cb.answer()
    user = ensure(cb.from_user)
    await safe_edit(cb.message, ui.profile(user), kb.back_menu())


@router.callback_query(F.data == "m:help")
async def cb_help(cb: CallbackQuery) -> None:
    await cb.answer()
    ensure(cb.from_user)
    await safe_edit(cb.message, ui.help_text(ai.ready()), kb.back_menu())


@router.callback_query(F.data == "m:ref")
async def cb_ref(cb: CallbackQuery) -> None:
    await cb.answer()
    user = ensure(cb.from_user)
    me = await cb.bot.me()
    link = f"https://t.me/{me.username}?start=ref_{user['ref_code']}"
    await safe_edit(
        cb.message,
        ui.ref_text(link, db.count_refs(cb.from_user.id),
                    db.count_pending_refs(cb.from_user.id), has_channel=bool(config.CHANNEL_ID)),
        kb.ref_kb(bool(config.CHANNEL_ID)),
    )


@router.callback_query(F.data == "ref:check")
async def cb_ref_check(cb: CallbackQuery) -> None:
    """Кнопка «я подписался» из экрана рефералки: проверка и бонус другу."""
    result = await subscribed(cb.bot, cb.from_user.id, force=True)
    if result is False:
        await cb.answer("Не вижу подписки. Подпишись на канал и нажми ещё раз.", show_alert=True)
        return
    if result is None:
        await cb.answer("Не могу проверить подписку. Напиши в поддержку.", show_alert=True)
        return
    granted = await grant_ref_bonus(cb.bot, cb.from_user.id)
    await cb.answer("Готово, другу начислены запросы" if granted else "Бонус уже начислен ранее",
                    show_alert=True)
    user = db.get_user(cb.from_user.id)
    await safe_edit(cb.message, ui.welcome(user["first_name"] or "друг", user, ai.ready()),
                    kb.main_menu(user))


@router.message(Command("keys"))
async def cmd_keys(message: Message) -> None:
    """Служебное: состояние пула ключей. Только для ADMIN_ID из .env."""
    if not config.ADMIN_ID or message.from_user.id != config.ADMIN_ID:
        return
    arg = (message.text or "").split(maxsplit=1)
    if len(arg) > 1 and arg[1].strip().lower() == "check":
        await message.answer("🔑 Перепроверяю все ключи, это займёт несколько секунд…")
        ok = await ai.healthcheck()
        await message.answer(("✅ рабочий ключ найден. " if ok else "❌ ни один ключ не принят. ")
                             + ai.POOL.report())
        return
    await message.answer("🔑 " + ai.POOL.report() + f"\nПричина: {ai.POOL.last_reason()}")


# --- настройки -------------------------------------------------------------
@router.callback_query(F.data == "m:setup")
async def cb_setup(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    user = ensure(cb.from_user)
    await safe_edit(cb.message, ui.setup_text(user), kb.setup_kb())


@router.callback_query(F.data == "m:grades")
async def cb_grades(cb: CallbackQuery) -> None:
    await cb.answer()
    ensure(cb.from_user)
    await safe_edit(cb.message, "<b>В каком ты классе?</b>\n\nОт этого зависит, как я объясняю.",
                    kb.grades_kb())


@router.callback_query(F.data.startswith("gr:"))
async def cb_grade(cb: CallbackQuery) -> None:
    raw = cb.data.split(":", 1)[1]
    ensure(cb.from_user)
    if not raw.isdigit() or int(raw) not in config.GRADES:
        await cb.answer("Такого класса нет", show_alert=True)
        return
    db.set_grade(cb.from_user.id, int(raw))
    await cb.answer(f"Класс: {raw}")
    user = db.get_user(cb.from_user.id)
    await safe_edit(cb.message, ui.setup_text(user), kb.setup_kb())


@router.callback_query(F.data == "m:subjects")
async def cb_subjects(cb: CallbackQuery) -> None:
    await cb.answer()
    ensure(cb.from_user)
    await safe_edit(cb.message, "<b>Основной предмет</b>\n\nМожно менять в любой момент.",
                    kb.subjects_kb())


@router.callback_query(F.data.startswith("sub:"))
async def cb_subject(cb: CallbackQuery) -> None:
    key = cb.data.split(":", 1)[1]
    ensure(cb.from_user)
    if key not in config.SUBJECT_BY_KEY:
        await cb.answer("Такого предмета нет", show_alert=True)
        return
    db.set_subject(cb.from_user.id, key)
    label, emoji = config.SUBJECT_BY_KEY[key]
    await cb.answer(f"{emoji} {label}")
    user = db.get_user(cb.from_user.id)
    await safe_edit(cb.message, ui.setup_text(user), kb.setup_kb())


# --- прочее ----------------------------------------------------------------
@router.callback_query()
async def cb_stale(cb: CallbackQuery) -> None:
    await cb.answer("Кнопка устарела. Открой меню: /menu")


@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    if await state.get_state() is not None:
        return
    user = ensure(message.from_user)
    await message.answer(
        "Пришли задание: фото или текст. Я разберу по шагам.\n\n"
        "Если нужны настройки — жми «Класс и предмет».",
        reply_markup=kb.main_menu(user),
    )


# --- обязательная подписка на канал ----------------------------------------
_SUB_CACHE: dict[int, tuple[bool, float]] = {}
SUB_TTL = 600.0


async def subscribed(bot, user_id: int, force: bool = False) -> bool | None:
    """True — подписан, False — нет, None — проверить не смогли."""
    if not config.REQUIRE_SUBSCRIPTION or not config.CHANNEL_ID:
        return True
    now = time.monotonic()
    if not force:
        cached = _SUB_CACHE.get(user_id)
        if cached and now - cached[1] < SUB_TTL:
            return cached[0]
    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("проверка подписки не удалась: %s", exc)
        return None
    ok = member.status in ("member", "administrator", "creator")
    _SUB_CACHE[user_id] = (ok, now)
    return ok


def gate_text() -> str:
    return (
        "📢 <b>Сначала подпишись на наш канал</b>\n\n"
        "Это одно нажатие — и бот открывается полностью: фото задания, разбор по шагам, "
        "проверка решения.\n\n"
        f"Канал: {config.CHANNEL_URL or config.CHANNEL_ID}\n\n"
        "Нажми «Подписаться», потом «Я подписался» — проверю и пущу дальше."
    )


async def require_subscription(message: Message, bot, user_id: int) -> bool:
    """Пускает дальше, если подписка есть. Иначе показывает экран подписки."""
    state = await subscribed(bot, user_id)
    if state is True:
        await grant_ref_bonus(bot, user_id)
        return True
    if state is None:
        # бот не админ канала или сеть подвела — блокировать всех нельзя
        log.warning("подписку проверить не смог, пропускаю %s", user_id)
        return True
    await message.answer(gate_text(), reply_markup=kb.subscribe_kb(),
                         disable_web_page_preview=True)
    return False





async def grant_ref_bonus(bot, invited_id: int) -> bool:
    """Начисляет пригласившему +5 запросов, когда друг прошёл подписку. Один раз."""
    row = db.get_user(invited_id)
    if row is None or not row["referred_by"] or db.ref_bonus_paid(row):
        return False
    inviter_id = row["referred_by"]
    db.mark_ref_bonus(invited_id)
    total = db.add_requests(inviter_id, config.REF_REWARD_REQUESTS)
    try:
        await bot.send_message(
            inviter_id,
            f"🎁 Твой друг подписался на канал — начислено "
            f"<b>+{config.REF_REWARD_REQUESTS} запросов</b>.\n"
            f"Купленных запросов теперь: <b>{total}</b>.",
        )
    except Exception:  # noqa: BLE001
        log.info("не смог уведомить пригласившего %s", inviter_id)
    return True