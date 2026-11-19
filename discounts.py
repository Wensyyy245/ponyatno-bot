"""Скидки: процент + срок действия. Применяются к запросам и подписке.

Донат скидкой не трогаем — это поддержка, а не товар.
"""
from __future__ import annotations

import db


def current() -> tuple[int, str]:
    """(процент, до какого времени). (0, "") — скидки нет."""
    row = db.active_discount()
    if not row:
        return 0, ""
    return int(row["percent"]), str(row["until"])


def price(base: int) -> tuple[int, int]:
    """(итоговая цена в звёздах, процент скидки)."""
    percent, _ = current()
    if percent <= 0:
        return base, 0
    final = max(1, round(base * (100 - percent) / 100))
    return final, percent


def label(base: int) -> str:
    final, percent = price(base)
    if percent <= 0:
        return f"{final} ⭐"
    return f"{final} ⭐ (было {base}, −{percent}%)"


def human_until() -> str:
    _, until = current()
    if not until:
        return ""
    return until.replace("T", " ")[:16]
