"""Поиск провайдера для ключа: перебор OpenAI-совместимых шлюзов.

Многие сервисы выдают ключи вида `sk-...`, и угадать шлюз по префиксу нельзя.
Скрипт проверяет `{base}/models` и затем реальный ответ модели на нескольких адресах.

Запуск:  python find_provider.py [ключ]
Без аргумента берёт первый ключ из keys.txt или AI_API_KEY из .env.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

import config

KEYS_FILE = Path(__file__).resolve().parent / "keys.txt"
SEM = asyncio.Semaphore(5)

BASES = [
    ("aitunnel", "https://api.aitunnel.ru/v1"),
    ("proxyapi", "https://api.proxyapi.ru/openai/v1"),
    ("vsegpt", "https://api.vsegpt.ru/v1"),
    ("bothub", "https://bothub.chat/api/v2/openai/v1"),
    ("polza.ai", "https://polza.ai/api/v1"),
    ("gptunnel", "https://api.gptunnel.ru/v1"),
    ("openai", "https://api.openai.com/v1"),
    ("openrouter", "https://openrouter.ai/api/v1"),
    ("deepseek", "https://api.deepseek.com/v1"),
    ("groq", "https://api.groq.com/openai/v1"),
    ("together", "https://api.together.xyz/v1"),
    ("mistral", "https://api.mistral.ai/v1"),
    ("perplexity", "https://api.perplexity.ai"),
    ("xai", "https://api.x.ai/v1"),
    ("fireworks", "https://api.fireworks.ai/inference/v1"),
    ("aimlapi", "https://api.aimlapi.com/v1"),
    ("nebius", "https://api.nebius.ai/v1"),
    ("hyperbolic", "https://api.hyperbolic.xyz/v1"),
    ("novita", "https://api.novita.ai/v3/openai"),
    ("sambanova", "https://api.sambanova.ai/v1"),
    ("cerebras", "https://api.cerebras.ai/v1"),
    ("moonshot", "https://api.moonshot.cn/v1"),
    ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("302.ai", "https://api.302.ai/v1"),
    ("ohmygpt", "https://api.ohmygpt.com/v1"),
    ("yandex", "https://llm.api.cloud.yandex.net/v1"),
    ("replicate", "https://api.replicate.com/v1"),
]


def mask(k: str) -> str:
    return f"{k[:10]}…{k[-4:]}" if len(k) > 16 else k


def load_key() -> str:
    for arg in sys.argv[1:]:
        if arg.startswith(("sk-", "rk_", "r8_")):
            return arg.strip()
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                return text
    return config.AI_API_KEY


async def get_models(session, base: str, key: str) -> tuple[int, str, list[str]]:
    try:
        async with session.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"},
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            body = await r.text()
            if r.status != 200:
                return r.status, body[:80], []
            data = json.loads(body)
            ids = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
            return 200, f"{len(ids)} моделей", ids
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__, []


async def chat(session, base: str, key: str, model: str) -> tuple[int, str]:
    payload = {"model": model, "messages": [{"role": "user", "content": "ок"}], "max_tokens": 3}
    try:
        async with session.post(f"{base}/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {key}",
                                         "Content-Type": "application/json"},
                                timeout=aiohttp.ClientTimeout(total=25)) as r:
            body = await r.text()
            if r.status == 200:
                return 200, "модель ответила"
            try:
                err = json.loads(body)
                msg = (err.get("error") or {}).get("message") or err.get("detail") or body
            except Exception:  # noqa: BLE001
                msg = body
            return r.status, str(msg)[:90]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


async def check(session, name: str, base: str, key: str) -> dict:
    async with SEM:
        status, info, models = await get_models(session, base, key)
    result = {"name": name, "base": base, "status": status, "info": info, "models": models[:3]}
    if status == 200 and models:
        for model in models[:2]:
            async with SEM:
                cstatus, cinfo = await chat(session, base, key, model)
            result["chat_status"] = cstatus
            result["chat_info"] = cinfo
            result["model"] = model
            if cstatus == 200:
                break
    return result


async def main() -> int:
    key = load_key()
    if not key:
        print("нет ключа: передай аргументом или впиши в keys.txt")
        return 1
    print(f"ключ: {mask(key)} · проверяю {len(BASES)} шлюзов\n")

    async with aiohttp.ClientSession() as s:
        results = await asyncio.gather(*(check(s, n, b, key) for n, b in BASES))

    found = []
    for r in sorted(results, key=lambda x: (x["status"] != 200, x["name"])):
        status = r["status"]
        if status == 200:
            print(f"✓ {r['name']:12} {r['base']:45} {r['info']}")
            if r.get("chat_status") == 200:
                print(f"    └ модель {r.get('model')} отвечает — ЭТО ОН")
                found.append(r)
            else:
                print(f"    └ модели есть, чат: {r.get('chat_status')} {str(r.get('chat_info'))[:60]}")
        elif status in (401, 403):
            print(f"✗ {r['name']:12} {r['base']:45} {status} {r['info'][:50]}")
        elif status == 404:
            print(f"· {r['name']:12} {r['base']:45} 404 (нет такого адреса)")
        else:
            print(f"? {r['name']:12} {r['base']:45} {status or '—'} {r['info'][:50]}")

    print("\n" + "=" * 62)
    if found:
        r = found[0]
        print(f"Ключ жив у провайдера {r['name']}")
        print(f"  AI_BASE_URL={r['base']}")
        print(f"  AI_MODEL={r.get('model')}")
        return 0
    print("Ни один шлюз не принял ключ ни на /models, ни на чате.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
