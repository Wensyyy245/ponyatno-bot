"""Проверка ключей: каждый ключ против всех провайдеров + отдельная проверка Replicate.

Проверяет именно то, что нужно боту: даёт ли ключ ответ модели.
Запуск:  python probe_real.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

KEYS_FILE = Path(__file__).resolve().parent / "keys.txt"
REPORT = Path(__file__).resolve().parent / "data" / "probe_real.json"

BASES = [
    ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("openrouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    ("proxyapi", "https://api.proxyapi.ru/openai/v1", "gpt-4o-mini"),
    ("vsegpt", "https://api.vsegpt.ru/v1", "openai/gpt-4o-mini"),
]


def mask(k: str) -> str:
    return f"{k[:10]}…{k[-4:]}" if len(k) > 16 else k


def load_keys() -> list[str]:
    if not KEYS_FILE.exists():
        return []
    out, seen = [], set()
    for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
        key = line.strip()
        if not key or key.startswith("#") or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def looks_like(key: str) -> str:
    if key.startswith("sk-or-v1-"):
        return "OpenRouter"
    if key.startswith("sk-proj-"):
        return "OpenAI (проектный)"
    if key.startswith("rk_live_") or key.startswith("r8_"):
        return "Replicate"
    if key.startswith("sk-ant-"):
        return "Anthropic"
    if key.startswith("sk-"):
        return "похож на OpenAI (старый формат)"
    return "неизвестный формат"


async def chat_call(session, base: str, model: str, key: str) -> tuple[int, str]:
    payload = {"model": model, "messages": [{"role": "user", "content": "ок"}], "max_tokens": 3}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with session.post(f"{base}/chat/completions", json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=30)) as r:
            body = await r.text()
            if r.status == 200:
                return 200, "модель ответила"
            try:
                err = json.loads(body)
                msg = (err.get("error") or {}).get("message") or err.get("detail") or body
            except Exception:  # noqa: BLE001
                msg = body
            return r.status, str(msg)[:110]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


async def replicate_check(session, key: str) -> tuple[int, str]:
    """Replicate: GET https://api.replicate.com/v1/account с Bearer-токеном."""
    try:
        async with session.get("https://api.replicate.com/v1/account",
                               headers={"Authorization": f"Bearer {key}"},
                               timeout=aiohttp.ClientTimeout(total=30)) as r:
            body = await r.text()
            return r.status, body[:140]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


async def main() -> int:
    keys = load_keys()
    if not keys:
        print("keys.txt пуст")
        return 1

    alive: list[tuple[str, str, str]] = []
    async with aiohttp.ClientSession() as s:
        for key in keys:
            print(f"\n=== {mask(key)} · {looks_like(key)}")
            if key.startswith(("rk_live_", "r8_")):
                status, info = await replicate_check(s, key)
                print(f"  replicate.com/v1/account -> {status or '—'} {info[:110]}")
                if status == 200:
                    print("  ! ключ рабочий, но Replicate не даёт OpenAI-совместимый чат:")
                    print("    для фото-разбора он не подходит без отдельной интеграции")
                continue
            for name, base, model in BASES:
                status, info = await chat_call(s, base, model, key)
                print(f"  {name:11} {model:30} -> {status or '—'} {info[:80]}")
                if status == 200:
                    alive.append((key, base, model))
                    break
                if status in (429, 0):
                    await asyncio.sleep(1.5)

    print("\n" + "=" * 60)
    if alive:
        for key, base, model in alive:
            print(f"✓ рабочий: {mask(key)} · {base} · {model}")
    else:
        print("Рабочих ключей для фото-разбора нет.")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(
        [{"key": mask(k), "base": b, "model": m} for k, b, m in alive],
        ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if alive else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
