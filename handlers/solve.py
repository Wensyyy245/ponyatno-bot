"""Разбор домашки: фото, текст, «проще», «похожая задача», проверка решения."""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from PIL import Image

import ai
import config
import db
import keyboards as kb
import offline
import render
import states
import store
import solver
import ui
from handlers.common import ensure, require_subscription, safe_edit

router = Router(name="solve")
log = logging.getLogger(__name__)

PHOTO_HINT = (
    "<b>Пришли фото задания</b>\n\n"
    "Чтобы я прочитал текст:\n"
    "• одно задание в кадре, а не вся страница\n"
    "• свет сбоку, без блика на бумаге\n"
    "• резко: телефон на уровне листа, а не под углом\n\n"
    "Или напиши задание текстом — кнопка ниже."
)

THINKING = "🤔 Думаю над задачей…"


def _cache_key(text: str | None, image: tuple[bytes, str] | None,
               subject: str, grade: int, mode: str) -> str:
    raw = f"{subject}|{grade}|{mode}|{(text or '').strip().lower()}"
    if image:
        raw += "|img:" + hashlib.sha256(image[0]).hexdigest()[:24]
    return hashlib.sha256(raw.encode()).hexdigest()


def _shrink_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Уменьшает фото перед отправкой в модель: меньше пикселей — меньше денег.

    Модель платит за площадь картинки, а 1024 px по длинной стороне хватает,
    чтобы прочитать текст задания.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        if max(img.size) > config.IMAGE_MAX_SIDE:
            img.thumbnail((config.IMAGE_MAX_SIDE, config.IMAGE_MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=config.IMAGE_QUALITY, optimize=True)
        shrunk = buf.getvalue()
        if len(shrunk) < len(data):
            log.info("фото ужато: %s → %s байт, %s", len(data), len(shrunk), img.size)
            return shrunk, "image/jpeg"
    except Exception:  # noqa: BLE001 — не смогли ужать, отправим как есть
        log.warning("не удалось уменьшить фото", exc_info=True)
    return data, mime


def no_ai_text() -> str:
    """Три разных причины — три разных сообщения. Врать про «ключ не вписан» нельзя."""
    st = ai.status()
    if st["state"] == "no_keys":
        return (
            "📸 Фото пока не читаю: в <code>.env</code> нет ключа AI, фото некому распознать.\n\n"
            "<b>Что делать</b>\n"
            "1. Напиши задание текстом — разберу прямо сейчас (математика считается офлайн).\n"
            "2. Впиши ключ AI в <code>.env</code> (поле <code>AI_API_KEY</code>) — "
            "инструкция в README, раздел «Ключ AI».\n\n"
            "Как только ключ появится, фото заработает без других изменений."
        )
    if st["state"] == "quota":
        return (
            "💳 Ключ AI рабочий, но на счету провайдера <b>нет средств</b>.\n\n"
            f"Ответ провайдера: <code>{html.escape(str(st['text'])[:200])}</code>\n\n"
            "Пополни баланс в кабинете провайдера — фото включится сразу, перезапуск не нужен.\n\n"
            "А пока пришли задание текстом: математика, проценты, уравнения и алгоритмы "
            "по предметам работают офлайн."
        )
    if st["state"] == "cooling":
        return (
            "⏳ Фото временно недоступно: провайдер ограничил частоту запросов, ключи остывают.\n\n"
            "Подожди пару минут и пришли фото снова. Текст работает прямо сейчас."
        )
    return (
        "📸 Ключи AI вписаны, но провайдер их <b>не принимает</b>.\n\n"
        f"Ответ провайдера: <code>{html.escape(str(st['text'])[:200])}</code>\n\n"
        "<b>Что это значит</b>\n"
        "ключ недействителен, отозван или выпущен для другого сервиса. Проверить можно так:\n"
        "<code>python liveai.py</code> — он покажет, какой провайдер принимает ключ.\n\n"
        "Пока фото недоступно, пришли задание текстом: математика, проценты, уравнения "
        "и алгоритмы по предметам работают офлайн."
    )


def _limit_or_none(user) -> str | None:
    left = db.solves_left(user)
    if left is not None and left <= 0:  # None — подписка, безлимит
        return ui.limit_text(user)
    return None


async def _send_answer(message: Message, user, answer: dict, *, subject: str, grade: int,
                       source: str, note: str = "", has_task: bool = True,
                       placeholder: Message | None = None) -> None:
    text = render.render(answer, grade=grade, subject=subject, source=source,
                         provider=answer.get("provider", "ai"), note=note)
    markup = kb.answer_kb(has_task)
    if placeholder is not None:
        try:
            await placeholder.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:  # noqa: BLE001 — сообщение могли удалить
            await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    db.use_solve(user["user_id"])
    db.add_xp(user["user_id"], config.XP_PER_SOLVE)
    db.log_solution(user["user_id"], subject, grade, source,
                    "explain", answer.get("provider", "ai"), ok=True)
    store.mark(user["user_id"])


async def process(message: Message, user, *, text: str | None = None,
                  image: tuple[bytes, str] | None = None,
                  mode: str = "explain", subject: str | None = None,
                  grade: int | None = None, source: str | None = None) -> bool:
    """Конвейер с экономией: кэш → офлайн → только потом AI.

    Порядок именно такой: математика считается локально за миллисекунды и не стоит
    ни копейки, повторная задача берётся из кэша, и только остальное уходит в модель.
    """
    subject = subject or user["subject"] or config.DEFAULT_SUBJECT
    grade = grade or user["grade"] or config.DEFAULT_GRADE
    source = source or ("photo" if image else "text")
    label = config.SUBJECT_BY_KEY.get(subject, ("Задание", "📌"))[0]

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:  # noqa: BLE001 — индикатор не критичен
        pass

    key = _cache_key(text, image, subject, grade, mode)
    cached = db.cache_get(key)
    if cached:
        log.info("ответ из кэша, без вызова AI")
        answer = json.loads(cached["payload"])
        answer["provider"] = f"{cached['provider']}+cache"
        await _send_answer(message, user, answer, subject=subject, grade=grade,
                           source=source, has_task=bool(text))
        if text:
            store.save(user["user_id"], text, source, subject, grade)
        return True

    answer: dict | None = None
    note = ""

    # бесплатный путь: математика и алгоритмы считаются локально
    if text and not image:
        answer = offline.try_solve(text, subject)

    placeholder: Message | None = None
    if answer is None:
        if not ai.ready():
            if image:
                await message.answer(no_ai_text(), reply_markup=kb.solve_prompt_kb())
            else:
                await message.answer(
                    "Не смог разобрать это офлайн, а AI сейчас недоступен.\n\n"
                    "Офлайн я решаю примеры, уравнения, проценты, дроби и объясняю алгоритмы "
                    "типовых заданий.",
                    reply_markup=kb.solve_prompt_kb(),
                )
            return False

        if db.ai_calls_today() >= config.AI_DAILY_CALL_LIMIT:
            log.warning("дневной лимит AI исчерпан: %s", db.ai_calls_today())
            await message.answer(
                "Сегодня бот уже обработал максимум задач через AI.\n\n"
                "Математика и алгоритмы по-прежнему работают — пришли задание текстом.",
                reply_markup=kb.solve_prompt_kb(),
            )
            return False

        placeholder = await message.answer(THINKING)
        payload_image = _shrink_image(*image) if image else None
        try:
            answer = dict(await ai.ask(text, grade=grade, subject=label, mode=mode,
                                       image=payload_image, student=None))
            db.ai_call_bump()
        except ai.QuotaError as exc:
            log.warning("AI quota: %s", exc)
            note = f"AI-провайдер не даёт запросы: {exc}. Показываю офлайн-разбор."
        except ai.AIError as exc:
            log.warning("AI error: %s", exc)
            note = f"AI не ответил ({exc}). Показываю офлайн-разбор."
        except Exception:  # noqa: BLE001
            log.exception("AI сломался")
            note = "AI дал сбой. Показываю офлайн-разбор."

        if answer is None and text:
            answer = offline.try_solve(text, subject)

    if answer is None:
        text_out = no_ai_text() if image else (
            "Не смог разобрать это задание.\n\n"
            "Пришли его текстом — математику и типовые задания разберу офлайн."
        )
        if placeholder is not None:
            try:
                await placeholder.edit_text(text_out, reply_markup=kb.solve_prompt_kb())
                return False
            except Exception:  # noqa: BLE001
                pass
        await message.answer(text_out, reply_markup=kb.solve_prompt_kb())
        return False

    # в кэш кладём только то, за что заплатили токенами
    if placeholder is not None and not answer.get("provider", "").startswith(("mock", "offline")):
        try:
            db.cache_put(key, json.dumps({k: v for k, v in answer.items() if k != "provider"},
                                         ensure_ascii=False),
                         answer.get("provider", "ai"))
        except Exception:  # noqa: BLE001
            log.warning("не смог сохранить ответ в кэш", exc_info=True)

    await _send_answer(message, user, answer, subject=subject, grade=grade,
                       source=source, note=note, has_task=bool(text), placeholder=placeholder)
    if text:
        store.save(user["user_id"], text, source, subject, grade)
    return True


# --- точка входа -----------------------------------------------------------
@router.callback_query(F.data == "m:solve")
async def cb_solve(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = ensure(cb.from_user)
    if not await require_subscription(cb.message, cb.bot, cb.from_user.id):
        return
    limit = _limit_or_none(user)
    if limit:
        await safe_edit(cb.message, limit, kb.limit_kb())
        return
    await state.set_state(states.Task.photo)
    text = PHOTO_HINT if ai.ready() else PHOTO_HINT + "\n\n⚡ <i>" + html.escape(ai.status()["text"]) + ". Текст работает.</i>"
    await safe_edit(cb.message, text, kb.solve_prompt_kb())


@router.callback_query(F.data == "m:text")
async def cb_text(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = ensure(cb.from_user)
    if not await require_subscription(cb.message, cb.bot, cb.from_user.id):
        return
    limit = _limit_or_none(user)
    if limit:
        await safe_edit(cb.message, limit, kb.limit_kb())
        return
    await state.set_state(states.Task.text)
    await safe_edit(cb.message,
                    "<b>Напиши задание текстом</b>\n\n"
                    "Можно как в учебнике: «5(x−2) = 3x + 1» или «найди 20% от 150».\n"
                    "Формулы пиши обычными символами: x, +, −, *, /, ^, =.\n\n"
                    "<i>Например: x^2 − 5x + 6 = 0</i>",
                    kb.back_menu())


@router.callback_query(F.data == "m:demo")
async def cb_demo(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer("Показываю пример")
    user = ensure(cb.from_user)
    if _limit_or_none(user):
        await safe_edit(cb.message, "Лимит на сегодня выбран — попробуй завтра.", kb.limit_kb())
        return
    await state.clear()
    demo = "Реши уравнение: 5(x - 2) = 3x + 1"
    await cb.message.answer(f"<b>Пример задания:</b> <code>{html.escape(demo)}</code>")
    await process(cb.message, user, text=demo, source="demo")


@router.message(states.Task.text, F.text)
async def on_text(message: Message, state: FSMContext) -> None:
    user = ensure(message.from_user)
    if not await require_subscription(message, message.bot, message.from_user.id):
        return
    task = (message.text or "").strip()
    if len(task) < 2:
        await message.answer("Пусто. Напиши задание словами или символами.")
        return
    if len(task) > config.MAX_TEXT_LEN:
        await message.answer(f"Слишком длинно ({len(task)} символов). "
                             f"Пришли до {config.MAX_TEXT_LEN} — обычно достаточно одного задания.")
        return
    limit = _limit_or_none(user)
    if limit:
        await state.clear()
        await message.answer(limit, reply_markup=kb.limit_kb())
        return
    cd = store.cooldown_left(message.from_user.id, config.SOLVE_COOLDOWN_SEC)
    if cd > 0:
        await message.answer(f"Секунду, ещё обрабатываю предыдущее 🙂 ({cd:.1f} с)")
        return
    await state.clear()
    await process(message, user, text=task, source="text")


@router.message(F.photo | F.document)
async def on_photo(message: Message, state: FSMContext) -> None:
    user = ensure(message.from_user)
    if not await require_subscription(message, message.bot, message.from_user.id):
        return
    limit = _limit_or_none(user)
    if limit:
        await message.answer(limit, reply_markup=kb.limit_kb())
        return
    if not ai.ready():
        await message.answer(no_ai_text(), reply_markup=kb.solve_prompt_kb())
        return

    if message.photo:
        file_id, size = message.photo[-1].file_id, message.photo[-1].file_size or 0
        mime = "image/jpeg"
    else:
        doc = message.document
        mime = (doc.mime_type or "") if doc else ""
        if not mime.startswith("image/"):
            await message.answer("Это не картинка. Пришли фото задания или текст.")
            return
        file_id, size = doc.file_id, doc.file_size or 0

    if size > config.MAX_PHOTO_MB * 1024 * 1024:
        await message.answer(f"Фото больше {config.MAX_PHOTO_MB} МБ. Пересними покачественнее, "
                             "но поменьше — или напиши задание текстом.")
        return

    cd = store.cooldown_left(message.from_user.id, config.SOLVE_COOLDOWN_SEC)
    if cd > 0:
        await message.answer(f"Секунду, ещё обрабатываю предыдущее 🙂 ({cd:.1f} с)")
        return

    buffer = io.BytesIO()
    try:
        await message.bot.download(file_id, destination=buffer)
    except Exception:  # noqa: BLE001
        log.exception("не смог скачать фото")
        await message.answer("Не получилось скачать фото. Попробуй ещё раз.")
        return

    data = buffer.getvalue()
    if not data:
        await message.answer("Файл пустой — пересними.")
        return

    await state.clear()
    await process(message, user, image=(data, mime), source="photo")


# --- повторные объяснения --------------------------------------------------
async def _rerun(cb: CallbackQuery, mode: str) -> None:
    user = ensure(cb.from_user)
    if not await require_subscription(cb.message, cb.bot, cb.from_user.id):
        return
    last = store.get(cb.from_user.id)
    if not last or not last.get("text"):
        await cb.answer()
        await cb.message.answer(
            "Для этого нужен текст задания — с фото я его не сохраняю (и это правильно, "
            "это твои личные файлы).\n\nПришли задание текстом или заново фото.",
            reply_markup=kb.solve_prompt_kb(),
        )
        return
    if _limit_or_none(user):
        await cb.answer()
        await cb.message.answer(ui.limit_text(user), reply_markup=kb.limit_kb())
        return
    await cb.answer("Секунду…")
    await process(cb.message, user, text=last["text"], mode=mode,
                  subject=last["subject"], grade=last["grade"], source=last["source"])


@router.callback_query(F.data == "a:simpler")
async def cb_simpler(cb: CallbackQuery) -> None:
    await _rerun(cb, "simpler")


@router.callback_query(F.data == "a:similar")
async def cb_similar(cb: CallbackQuery) -> None:
    await _rerun(cb, "similar")


# --- проверка решения ------------------------------------------------------
@router.callback_query(F.data == "m:check")
@router.callback_query(F.data == "a:check")
async def cb_check(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = ensure(cb.from_user)
    if _limit_or_none(user):
        await safe_edit(cb.message, ui.limit_text(user), kb.limit_kb())
        return
    last = store.get(cb.from_user.id)
    if last and last.get("text"):
        await state.set_state(states.Task.check_answer)
        await state.update_data(task=last["text"], subject=last["subject"], grade=last["grade"])
        await safe_edit(
            cb.message,
            "<b>Проверка решения</b>\n\n"
            f"Задание: <code>{html.escape(last['text'][:200])}</code>\n\n"
            "Пришли свой ответ или всё решение — найду ошибку, если она есть.",
            kb.back_menu(),
        )
        return
    await state.set_state(states.Task.check_task)
    await safe_edit(
        cb.message,
        "<b>Проверка решения</b>\n\n"
        "Шаг 1 из 2. Пришли задание текстом.\n\n"
        "<i>Например: x^2 − 5x + 6 = 0</i>",
        kb.back_menu(),
    )


@router.message(states.Task.check_task, F.text)
async def on_check_task(message: Message, state: FSMContext) -> None:
    task = (message.text or "").strip()
    if len(task) < 2:
        await message.answer("Нужно задание. Пришли его текстом.")
        return
    await state.update_data(task=task[: config.MAX_TEXT_LEN])
    await state.set_state(states.Task.check_answer)
    await message.answer("<b>Шаг 2 из 2.</b> Теперь пришли свой ответ или решение.")


@router.message(states.Task.check_answer, F.text)
async def on_check_answer(message: Message, state: FSMContext) -> None:
    user = ensure(message.from_user)
    data = await state.get_data()
    task = data.get("task") or ""
    student = (message.text or "").strip()
    if not student:
        await message.answer("Пусто. Пришли свой ответ.")
        return
    await state.clear()

    if ai.ready():
        try:
            answer = dict(await ai.ask(task, grade=user["grade"], subject=config.SUBJECT_BY_KEY
                                       .get(user["subject"], ("Задание",))[0],
                                       mode="check", student=student))
            await _send_answer(message, user, answer, subject=user["subject"] or config.DEFAULT_SUBJECT,
                               grade=user["grade"], source="check", has_task=False)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("AI check упал: %s", exc)

    result = solver.check_student_answer(task, student)
    if result["ok"] is None:
        await message.answer(
            "Не смог проверить автоматически: " + html.escape(result["reason"]) +
            ".\n\nПришли задание и ответ текстом — например «2x + 3 = 7» и «x = 2».",
            reply_markup=kb.solve_prompt_kb(),
        )
        return

    if result["ok"]:
        body = ("✅ <b>Сходится.</b> Ответ совпал с правильным.\n\n"
                f"<b>Проверка:</b> {html.escape(result['answer'] if 'answer' in result else result['truth'])}")
    else:
        steps = "\n".join(f"<b>{i}.</b> {html.escape(s)}" for i, s in
                          enumerate(result.get("steps", [])[:8], 1))
        body = (f"❌ <b>Не сходится.</b> Правильный ответ: "
                f"<code>{html.escape(result['truth'])}</code>\n\n"
                + (f"<b>Как решается</b>\n{steps}\n\n" if steps else "")
                + "<i>Найди, на каком шаге разошлось с твоим решением.</i>")

    db.use_solve(user["user_id"])
    db.add_xp(user["user_id"], config.XP_PER_SOLVE // 2)
    db.log_solution(user["user_id"], user["subject"], user["grade"], "check", "offline-math", True)
    store.mark(user["user_id"])
    await message.answer(body, reply_markup=kb.answer_kb(False))
