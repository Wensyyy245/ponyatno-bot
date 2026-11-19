"""Офлайн-разбор без AI: математика через solver, остальное — алгоритм по типу задачи."""
from __future__ import annotations

import json
import re
from pathlib import Path

import solver

BANK_PATH = Path(__file__).resolve().parent / "content" / "algorithms.json"

with open(BANK_PATH, encoding="utf-8") as f:
    _BANK = json.load(f)["items"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def find_algorithm(text: str, subject: str | None = None) -> dict | None:
    low = _norm(text)
    best, best_score = None, 0
    for item in _BANK:
        score = sum(1 for key in item["keys"] if key in low)
        if score == 0:
            continue
        if subject and item["subject"] == subject:
            score += 1
        if score > best_score:
            best, best_score = item, score
    return best


def _as_answer(data: dict, provider: str) -> dict:
    return {
        "what": data.get("given", ""),
        "steps": data.get("steps", []),
        "answer": data.get("answer", ""),
        "hint": "",
        "similar": "",
        "provider": provider,
    }


def try_solve(text: str, subject: str | None) -> dict | None:
    """Возвращает разбор или None, если офлайн не справляемся."""
    text = (text or "").strip()
    if len(text) < 3:
        return None

    if subject in (None, "math", "phys", "chem", "inf"):
        try:
            result = solver.solve_text(text)
            answer = _as_answer(result, "offline-math")
            answer["hint"] = "Подставь ответ обратно в условие — сходится?"
            return answer
        except solver.MathError:
            pass

    algo = find_algorithm(text, subject)
    if algo:
        return {
            "what": f"Похоже на задание: {algo['title'].lower()}",
            "steps": algo["steps"],
            "answer": "",
            "hint": "Пройди по шагам со своими числами — и получишь ответ.",
            "similar": "",
            "provider": "offline-algo",
            "algorithm": algo["title"],
        }
    return None


def has_algorithm(text: str, subject: str | None = None) -> bool:
    return find_algorithm(text, subject) is not None
