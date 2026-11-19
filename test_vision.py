"""Живая проверка фото-режима через наш собственный конвейер ai.ask().

Рисует картинку с уравнением и прогоняет её ровно так, как это сделает бот.
Запуск:  python test_vision.py
"""
from __future__ import annotations

import asyncio
import io
import sys

from PIL import Image, ImageDraw, ImageFont

import ai
import render

TASK = "5(x - 2) = 3x + 1"


def make_image() -> bytes:
    img = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("arial.ttf", 46)
        small = ImageFont.truetype("arial.ttf", 28)
    except Exception:  # noqa: BLE001
        big = small = ImageFont.load_default()
    draw.text((40, 30), "Решите уравнение:", fill="black", font=small)
    draw.text((40, 110), TASK, fill="black", font=big)
    draw.text((40, 220), "8 класс, алгебра", fill="gray", font=small)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def main() -> int:
    print(f"провайдер: {ai.config.AI_BASE_URL} · модель: {ai.config.AI_MODEL}")
    print(f"ключей: {len(ai.config.ai_keys())} · живых: {ai.POOL.stats()['alive']}\n")

    data = make_image()
    print(f"отправляю фото ({len(data)} байт) с задачей {TASK}…\n")
    try:
        answer = await ai.ask(None, grade=8, subject="Математика",
                              image=(data, "image/jpeg"))
    except Exception as exc:  # noqa: BLE001
        print(f"✗ ошибка: {type(exc).__name__}: {exc}")
        return 1

    print("=== что вернула модель ===")
    print("дано:   ", answer.get("what"))
    for i, step in enumerate(answer.get("steps", []), 1):
        print(f"шаг {i}:  ", step[:120])
    print("ответ:  ", answer.get("answer"))
    print("проверка:", answer.get("hint"))
    print("\n=== как это увидит ученик в Telegram ===")
    print(render.render(answer, grade=8, subject="math", source="photo",
                        provider=answer.get("provider", "ai"))[:1200])

    text = " ".join(str(answer.get(k, "")) for k in ("answer", "steps", "what"))
    ok = ("5,5" in text or "5.5" in text or "11/2" in text)
    print("\n" + ("✓ модель прочитала фото и решила верно (x = 5,5)" if ok
                  else "! в ответе не видно x = 5,5 — проверь разбор глазами"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
