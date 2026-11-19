"""Тексты интерфейса «ПОНЯТНО»."""
from __future__ import annotations

import html

import config
import db


def bar(value: int, total: int, width: int = 10) -> str:
    total = max(total, 1)
    filled = min(width, round(value / total * width))
    return "▰" * filled + "▱" * (width - filled)


def subject_label(user) -> str:
    label, emoji = config.SUBJECT_BY_KEY.get(user["subject"] or config.DEFAULT_SUBJECT,
                                             ("Не выбран", "📚"))
    return f"{emoji} {label}"


def limits_line(user) -> str:
    if db.is_pro(user):
        return f"♾ <b>Подписка</b> · безлимит · осталось {db.pro_days_left(user)} дн."
    free = db.daily_free_left(user)
    paid = db.requests_left(user)
    return f"🎟 Сегодня: <b>{free}</b> из {config.FREE_SOLVES_PER_DAY} · куплено: <b>{paid}</b>"


def welcome(name: str, user, ai_on: bool) -> str:
    safe = html.escape(name or "друг")
    mode = ("🤖 Разбор по фото включён" if ai_on
            else "⚡ Офлайн-режим: текст и математика (фото включится после ключа AI)")
    return (
        f"<b>{config.BRAND}</b> · {config.TAGLINE}\n\n"
        f"Привет, <b>{safe}</b>. Пришли фото задания или напиши его текстом — "
        f"я разберу по шагам: что дано, как решать и почему именно так.\n\n"
        f"<b>Твой профиль</b>\n"
        f"🎓 {user['grade']} класс · {subject_label(user)}\n"
        f"{limits_line(user)}\n"
        f"{mode}\n\n"
        "<b>Как пользоваться</b>\n"
        f"1. Каждый день бесплатно {config.FREE_SOLVES_PER_DAY} разбора\n"
        "2. Закончились — можно купить пакет запросов или взять безлимит\n"
        "3. За друга, который подпишется на канал, — ещё 5 запросов\n\n"
        "<i>Я объясняю, а не пишу за тебя: контрольную всё равно придётся решать самому. "
        "Ответы проверяй — даже я ошибаюсь.</i>"
    )


def profile(user) -> str:
    xp = user["xp"] or 0
    lvl = xp // config.XP_LEVEL + 1
    refs = db.count_refs(user["user_id"])
    if db.is_pro(user):
        access = (f"♾ <b>Безлимит</b> · осталось <b>{db.pro_days_left(user)}</b> дн.\n"
                  "запросы не списываются")
    else:
        access = (f"🎟 Бесплатных сегодня: <b>{db.daily_free_left(user)}</b> из "
                  f"{config.FREE_SOLVES_PER_DAY}\n"
                  f"📦 Купленных запросов: <b>{db.requests_left(user)}</b> (не сгорают)")
    return (
        f"<b>Профиль</b>\n\n"
        f"👤 {html.escape(user['first_name'] or 'без имени')}"
        + (f" · @{html.escape(user['username'])}" if user["username"] else "") + "\n"
        f"🎓 {user['grade']} класс · {subject_label(user)}\n\n"
        f"<b>Уровень {lvl}</b> · {xp} XP\n"
        f"<code>{bar(xp % config.XP_LEVEL, config.XP_LEVEL)}</code> {xp % config.XP_LEVEL}/{config.XP_LEVEL}\n\n"
        f"🔥 Серия: <b>{user['streak'] or 0}</b> дн. подряд\n"
        f"📚 Разборов всего: <b>{user['solves_total'] or 0}</b>\n"
        f"🎁 Друзей пришло: <b>{refs}</b>\n"
        f"💛 Поддержка: <b>{user['donated'] or 0}</b> ⭐\n\n"
        f"<b>Доступ</b>\n{access}"
    )


def help_text(ai_on: bool) -> str:
    mode = (
        "🤖 <b>AI-режим включён.</b> Читаю фото, понимаю текст задачи, объясняю по шагам."
        if ai_on else
        "⚡ <b>Сейчас офлайн-режим.</b> Работают примеры, уравнения, проценты, дроби, "
        "а также алгоритмы решения типовых заданий по 11 предметам."
    )
    packs = " · ".join(f"{n} за {s} ⭐" for n, s in config.REQUEST_PACKS.values())
    subs = " · ".join(f"{d} дн. за {s} ⭐" for d, s, _ in config.SUB_PLANS.values())
    return (
        "<b>Как это работает</b>\n\n"
        f"{mode}\n\n"
        "<b>Сколько стоит</b>\n"
        f"• бесплатно каждый день: <b>{config.FREE_SOLVES_PER_DAY}</b> разбора\n"
        f"• пакеты запросов (не сгорают): {packs}\n"
        f"• подписка безлимит: {subs}\n"
        f"• за друга, подписанного на канал: <b>+{config.REF_REWARD_REQUESTS}</b> запросов\n\n"
        "<b>Что можно прислать</b>\n"
        "• фото страницы или одного задания\n"
        "• текст задачи\n"
        "• своё решение — покажу, где ошибка\n\n"
        "<b>Честно о границах</b>\n"
        "• сочинения и проекты целиком не пишу\n"
        "• сложное могу объяснить неточно — сверяйся с учебником\n"
        "• фото храню только в момент обработки"
    )


def setup_text(user) -> str:
    return (
        "<b>Класс и предмет</b>\n\n"
        f"Сейчас: <b>{user['grade']} класс</b> · {subject_label(user)}\n\n"
        "Класс влияет на то, как я объясняю: в 5 классе — простыми словами, "
        "в 10–11 — с формулами. Предмет помогает выбрать нужный способ решения."
    )


def limit_text(user) -> str:
    balance = db.requests_left(user)
    tail = (f"📦 У тебя ещё есть <b>{balance}</b> купленных запросов — они пойдут в дело "
            "после бесплатных.\n\n" if balance else "")
    return (
        f"🎟 Бесплатные разборы на сегодня закончились — их было {config.FREE_SOLVES_PER_DAY}.\n\n"
        f"{tail}"
        "<b>Что дальше</b>\n"
        "• завтра утром бесплатные снова начислятся\n"
        f"• купить пакет запросов — от {min(c for c, _ in config.REQUEST_PACKS.values())} шт.\n"
        f"• взять безлимит на 30 дней — {config.SUB_PLANS['sub30'][1]} ⭐\n"
        f"• позвать друга, подписанного на канал — <b>+{config.REF_REWARD_REQUESTS}</b> запросов"
    )


def ref_text(link: str, refs: int, pending: int = 0, has_channel: bool = True) -> str:
    channel = ""
    if has_channel:
        channel = (
            "\n<b>Важно</b>: друг должен подписаться на канал — тогда тебе придёт "
            f"<b>+{config.REF_REWARD_REQUESTS} запросов</b>.\n"
        )
    tail = f"\nОжидают подтверждения: <b>{pending}</b>" if pending else ""
    return (
        "<b>Позвать друга</b>\n\n"
        f"За друга, который зайдёт по ссылке и подпишется на канал, — "
        f"<b>+{config.REF_REWARD_REQUESTS} запросов</b> тебе.\n"
        f"{channel}\n"
        f"Твоя ссылка:\n<code>{html.escape(link)}</code>\n\n"
        f"Уже пришло друзей: <b>{refs}</b>{tail}"
    )
