"""Проверка ключа AI: какой провайдер отвечает, какие модели с картинками доступны.

Запуск:  python aicheck.py
Ключ не печатается.
"""
from __future__ import annotations

import asyncio
import sys

import aiohttp

import config

CANDIDATES = [
    ("proxyapi", "https://api.proxyapi.ru/openai/v1"),
    ("vsegpt", "https://api.vsegpt.ru/v1"),
    ("openrouter", "https://openrouter.ai/api/v1"),
    ("deepseek", "https://api.deepseek.com/v1"),
]

VISION_HINTS = ("4o", "vision", "vl", "qwen", "gemini", "claude", "gigachat", "llava", "pixtral")


async def probe(name: str, base: str) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {config.AI_API_KEY}"}
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{base}/models", headers=headers) as resp:
                if resp.status != 200:
                    text = (await resp.text())[:120]
                    return False, f"HTTP {resp.status}: {text}"
                data = await resp.json()
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

    models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
    vision = [m for m in models if any(h in m.lower() for h in VISION_HINTS)]
    print(f"✓ {name}: {len(models)} моделей, с картинками похоже на: "
          f"{', '.join(vision[:6]) if vision else '—'}")
    if config.AI_MODEL not in models and models:
        print(f"  ! {config.AI_MODEL} нет в списке — возможно, нужна другая модель")
    return True, base


async def main() -> int:
    if not config.AI_API_KEY:
        print("✗ AI_API_KEY пуст в .env")
        return 1
    print(f"Ключ: {config.AI_API_KEY[:6]}…{config.AI_API_KEY[-4:]} (модель {config.AI_MODEL})")
    ok_bases = []
    for name, base in CANDIDATES:
        ok, info = await probe(name, base)
        if ok:
            ok_bases.append((name, base))
        else:
            print(f"✗ {name}: {info}")
    if not ok_bases:
        print("\nНи один провайдер не принял ключ.")
        return 1
    print("\nРаботают: " + ", ".join(n for n, _ in ok_bases))
    if ok_bases[0][1] != config.AI_BASE_URL:
        print(f"! Пропиши в .env: AI_BASE_URL={ok_bases[0][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
