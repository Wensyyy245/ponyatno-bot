"""Отрисовка разбора в HTML для Telegram."""
from __future__ import annotations

import html

import config

MAX_LEN = 3900


def _e(text: str) -> str:
    return html.escape(str(text or "").strip())


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render(answer: dict, *, grade: int, subject: str, source: str,
           provider: str = "ai", note: str = "") -> str:
    label, emoji = config.SUBJECT_BY_KEY.get(subject, ("Задание", "📌"))
    src = "фото" if source == "photo" else "текстом"
    head = f"{emoji} <b>{_e(label)} · {grade} класс</b> · задача {src}"

    parts = [head]
    if answer.get("what"):
        parts += ["", f"<i>{_e(_clip(answer['what'], 400))}</i>"]

    steps = [s for s in answer.get("steps", []) if str(s).strip()]
    if steps:
        body = "\n".join(f"<b>{i}.</b> {_e(_clip(s, 500))}" for i, s in enumerate(steps[:12], 1))
        parts += ["", "<b>По шагам</b>", body]

    if answer.get("answer"):
        parts += ["", "<b>Ответ</b>", f"<blockquote>{_e(_clip(answer['answer'], 400))}</blockquote>"]

    if answer.get("hint"):
        parts += ["", f"<b>Проверь себя</b>\n{_e(_clip(answer['hint'], 300))}"]

    if answer.get("similar"):
        parts += ["", f"<b>Похожая задача</b>\n{_e(_clip(answer['similar'], 300))}"]

    tail = []
    if provider.startswith("offline"):
        tail.append("⚡ <i>Разбор без AI: по алгоритму из банка. С фото помогает только AI-режим.</i>")
    if note:
        tail.append(_e(note))
    if tail:
        parts += ["", "———", *tail]

    text = "\n".join(parts)
    return _clip(text, MAX_LEN)


def render_algorithm_list() -> str:
    return ""
