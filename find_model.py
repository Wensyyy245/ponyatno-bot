"""Находит рабочую модель и проверяет ключ настоящим запросом (не /models).

Запуск:  python find_model.py
"""
from __future__ import annotations

import asyncio
import sys

import aiohttp

import config

BASE = "https://openrouter.ai/api/v1"
CANDIDATE_HINTS = ("4o-mini", "4o", "gemini", "qwen", "claude", "gpt", "flash")


async def list_models(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(f"{BASE}/models", timeout=aiohttp.ClientTimeout(total=25)) as resp:
        if resp.status != 200:
            print(f"! /models ответил {resp.status}")
            return []
        data = await resp.json()
    return data.get("data", [])


async def try_model(session: aiohttp.ClientSession, key: str, model: str) -> tuple[bool, str]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Скажи одно слово: ок"}],
        "max_tokens": 5,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with session.post(f"{BASE}/chat/completions", json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            body = (await resp.text())[:160]
            if resp.status == 200:
                data = await resp.json()
                text = data["choices"][0]["message"]["content"]
                return True, str(text)[:40]
            return False, f"HTTP {resp.status}: {body}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"


async def main() -> int:
    if not config.AI_API_KEY:
        print("AI_API_KEY пуст")
        return 1
    async with aiohttp.ClientSession() as session:
        models = await list_models(session)
        print(f"в каталоге {len(models)} моделей")
        vision = [m["id"] for m in models
                  if "image" in ((m.get("architecture") or {}).get("input_modalities") or [])]
        print(f"читают картинки: {len(vision)}")

        shortlist = [m for m in vision if any(h in m.lower() for h in CANDIDATE_HINTS)]
        shortlist.sort(key=lambda m: (
            float(((m.get("pricing") or {}).get("prompt") or 9e9)),
            len(m["id"]),
        ))
        shortlist = [m["id"] for m in shortlist][:6]
        if config.AI_MODEL in vision:
            shortlist.insert(0, config.AI_MODEL)

        print("\nПроверяю ключ на моделях:")
        for model in dict.fromkeys(shortlist):
            ok, info = await try_model(session, config.AI_API_KEY, model)
            mark = "✓" if ok else "✗"
            print(f" {mark} {model:45} {info}")
            if ok:
                print(f"\nРабочая пара: AI_BASE_URL={BASE}\nAI_MODEL={model}")
                return 0
    print("\nНи одна модель не ответила успешно — ключ, похоже, не принимается.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
