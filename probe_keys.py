"""Проверка ключей AI настоящим запросом к модели.

Прежняя версия смотрела в публичный /models — он отвечает 200 даже на мусорный
ключ, поэтому проверка врала. Здесь проверяется то, что важно: даёт ли ключ ответ модели.

Запуск:  python probe_keys.py            — проверить и обновить keys.txt + .env
         python probe_keys.py --dry      — только отчёт
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import aiohttp

import config

KEYS_FILE = Path(__file__).resolve().parent / "keys.txt"
ENV_FILE = Path(__file__).resolve().parent / ".env"
STATE_FILE = config.AI_KEYS_STATE
REPORT = Path(__file__).resolve().parent / "data" / "probe_report.json"

PROVIDERS = [
    ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("openrouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    ("proxyapi", "https://api.proxyapi.ru/openai/v1", "gpt-4o-mini"),
]
SEM = asyncio.Semaphore(3)


def mask(k: str) -> str:
    return f"{k[:7]}…{k[-4:]}" if len(k) > 14 else k


def load_keys() -> list[str]:
    if not KEYS_FILE.exists():
        return []
    out, seen = [], set()
    for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
        key = line.strip()
        if not key or key.startswith("#") or not key.startswith("sk-") or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


async def call(session: aiohttp.ClientSession, base: str, model: str,
               key: str) -> tuple[int, str]:
    payload = {"model": model, "messages": [{"role": "user", "content": "ок"}],
               "max_tokens": 3}
    try:
        async with session.post(f"{base}/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {key}"},
                                timeout=aiohttp.ClientTimeout(total=25)) as resp:
            body = await resp.text()
            if resp.status == 200:
                return 200, "модель ответила"
            try:
                err = json.loads(body)
                msg = (err.get("error") or {}).get("message") or err.get("detail") or body
            except Exception:  # noqa: BLE001
                msg = body
            return resp.status, str(msg)[:110]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


async def probe_key(session, key: str) -> tuple[str, str, str, str]:
    """→ (key, статус, провайдер, пояснение)."""
    last = ("", "нет ответа")
    for name, base, model in PROVIDERS:
        async with SEM:
            status, info = await call(session, base, model, key)
        if status == 200:
            return key, "ok", f"{name}/{model}", info
        last = (name, info)
        if status in (429, 0):
            await asyncio.sleep(1.5)
    return key, "dead", last[0], last[1]


async def main(dry: bool) -> int:
    keys = load_keys()
    if not keys:
        print("keys.txt пуст: вставь ключи по одному на строку и запусти снова.")
        return 1
    print(f"Проверяю {len(keys)} ключей настоящими запросами к модели…\n")

    async with aiohttp.ClientSession() as session:
        results = [await probe_key(session, k) for k in keys]

    alive = [k for k, st, _, _ in results if st == "ok"]
    for key, status, provider, info in results:
        mark = "✓" if status == "ok" else "✗"
        where = f" [{provider}]" if status == "ok" else ""
        print(f" {mark} {mask(key)} — {info[:70]}{where}")

    print(f"\nживых: {len(alive)} из {len(keys)}")
    if not alive:
        print("Ни один ключ не даёт ответ модели. Бот останется в офлайн-режиме.")
        print("Проверь формат: OpenAI — sk-proj-…, OpenRouter — sk-or-v1-…, "
              "ProxyAPI — ключ из личного кабинета.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(
        [{"key": mask(k), "status": s, "provider": p, "info": i} for k, s, p, i in results],
        ensure_ascii=False, indent=2), encoding="utf-8")

    if dry:
        return 0 if alive else 1

    KEYS_FILE.write_text("\n".join(alive) + ("\n" if alive else ""), encoding="utf-8")
    env = ENV_FILE.read_text(encoding="utf-8")
    value = ",".join(alive)
    if re.search(r"^AI_API_KEYS=.*$", env, flags=re.MULTILINE):
        env = re.sub(r"^AI_API_KEYS=.*$", f"AI_API_KEYS={value}", env, flags=re.MULTILINE)
    else:
        env += f"\nAI_API_KEYS={value}\n"
    if alive:
        env = re.sub(r"^AI_API_KEY=.*$", f"AI_API_KEY={alive[0]}", env, flags=re.MULTILINE)
    ENV_FILE.write_text(env, encoding="utf-8")
    STATE_FILE.unlink(missing_ok=True)  # пул перепроверит ключи с чистого листа
    print(f"Обновил keys.txt и .env. Живых ключей: {len(alive)}. "
          "Перезапусти бота — фото включится.")
    return 0 if alive else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry" in sys.argv)))
