"""Короткая память процесса: последняя задача и антифлуд."""
from __future__ import annotations

import time

LAST: dict[int, dict] = {}
_last: dict[int, float] = {}


def save(user_id: int, text: str | None, source: str, subject: str, grade: int) -> None:
    LAST[user_id] = {"text": text, "source": source, "subject": subject, "grade": grade}


def get(user_id: int) -> dict | None:
    return LAST.get(user_id)


def cooldown_left(user_id: int, seconds: float) -> float:
    return max(0.0, seconds - (time.monotonic() - _last.get(user_id, 0.0)))


def mark(user_id: int) -> None:
    _last[user_id] = time.monotonic()
