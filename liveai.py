"""Живая проверка ключа AI: текст и фото. Ничего не пишет в состояние пула.

Запуск:  python liveai.py            — только проверка
         python liveai.py --save     — ещё и прописать рабочую пару в .env
Ключи в выводе маскируются.
"""
from __future__ import annotations

import asyncio
import base64
import io
import re
import sys
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

import config

ENV_FILE = Path(__file__).resolve().parent / ".env"

BASES = [
    "https://openrouter.ai/api/v1",
    "https://api.proxyapi.ru/openai/v1",
]
MODELS = [
    "openai/gpt-4o-mini",
    "gpt-4o-mini",
    "openai/gpt-4o",
    "google/gemini-2.0-flash-001",
    "qwen/qwen-2.5-vl-72b-instruct",
]


def mask(key: str) -> str:
    return f"{key[:7]}…{key[-4:]}" if len(key) > 14 else key


def make_task_image() -> bytes:
    img = Image.new("RGB", (900, 320), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 44)
        small = ImageFont.truetype("arial.ttf", 30)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
        small = font
    draw.text((40, 30), "Решите уравнение:", fill="black", font=small)
    draw.text((40, 110), "5(x - 2) = 3x + 1", fill="black", font=font)
    draw.text((40, 230), "8 класс, алгебра", fill="gray", font=small)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def post(session, base: str, model: str, key: str, content) -> tuple[bool, str, dict | None]:
    payload = {"model": model, "messages": [{"role": "user", "content": content}],
               "max_tokens": 700, "temperature": 0.2}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with session.post(f"{base}/chat/completions", json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=60)) as resp:
            body = await resp.text()
            if resp.status == 200:
                data = await resp.json()
                return True, "ok", data
            return False, f"HTTP {resp.status}: {body[:120]}", None
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}", None


async def main(save: bool) -> int:
    keys = config.ai_keys()
    if not keys:
        print("ключей нет в .env")
        return 1
    print(f"ключей: {len(keys)} · модель в конфиге: {config.AI_MODEL}")
    image_b64 = base64.b64encode(make_task_image()).decode()

    async with aiohttp.ClientSession() as session:
        for base in BASES:
            for model in MODELS:
                ok, info, data = await post(session, base, model, keys[0],
                                            "Ответь одним словом: работает?")
                print(f" {'✓' if ok else '✗'} {base.split('//')[1][:28]:28} {model:34} {info[:70]}")
                if not ok:
                    if "401" in info or "403" in info:
                        break  # ключ не к этой площадке
                    continue
                # ключ и модель работают — проверяем зрение
                vision_task = [
                    {"type": "text", "text": "Что написано на картинке? Реши уравнение по шагам."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ]
                v_ok, v_info, v_data = await post(session, base, model, keys[0], vision_task)
                print(f"   зрение: {'✓' if v_ok else '✗'} {v_info[:80]}")
                if v_ok:
                    text = v_data["choices"][0]["message"]["content"]
                    print("   ответ модели:", re.sub(r"\s+", " ", str(text))[:300])
                    if "5,5" in str(text) or "5.5" in str(text) or "11/2" in str(text):
                        print("   ✓ уравнение решено верно (x = 5,5)")
                    else:
                        print("   ! в ответе не видно x = 5,5 — проверь вручную")
                    if save:
                        env = ENV_FILE.read_text(encoding="utf-8")
                        env = re.sub(r"^AI_BASE_URL=.*$", f"AI_BASE_URL={base}", env, flags=re.MULTILINE)
                        env = re.sub(r"^AI_MODEL=.*$", f"AI_MODEL={model}", env, flags=re.MULTILINE)
                        ENV_FILE.write_text(env, encoding="utf-8")
                        print(f"\nЗаписал в .env: {base} · {model}")
                    return 0
                await asyncio.sleep(1.0)
    print("\nЖивой AI-режим не подтверждён. Бот останется в офлайн-режиме, ключи будут "
          "проверяться ротацией автоматически.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--save" in sys.argv)))
