"""Проверка схем авторизации: возможно, шлюз ждёт ключ не в Bearer.

Запуск:  python probe_headers.py
"""
from __future__ import annotations

import asyncio
import sys

import aiohttp

import config

KEY = config.AI_API_KEY
BASE = "https://api.proxyapi.ru/openai/v1"
TARGETS = [
    ("proxyapi", "https://api.proxyapi.ru/openai/v1"),
    ("vsegpt", "https://api.vsegpt.ru/v1"),
    ("aitunnel", "https://api.aitunnel.ru/v1"),
    ("polza", "https://polza.ai/api/v1"),
    ("bothub", "https://bothub.chat/api/v2/openai/v1"),
]
SCHEMES = {
    "Bearer": lambda k: {"Authorization": f"Bearer {k}"},
    "raw": lambda k: {"Authorization": k},
    "api-key": lambda k: {"api-key": k},
    "x-api-key": lambda k: {"x-api-key": k},
    "X-Auth-Token": lambda k: {"X-Auth-Token": k},
    "token": lambda k: {"Authorization": f"Token {k}"},
}


async def main() -> int:
    print(f"ключ: {KEY[:10]}…{KEY[-4:]}\n")
    async with aiohttp.ClientSession() as s:
        for name, base in TARGETS:
            print(f"— {name} ({base})")
            for scheme, build in SCHEMES.items():
                headers = {**build(KEY), "Content-Type": "application/json"}
                payload = {"model": "gpt-4o-mini",
                           "messages": [{"role": "user", "content": "ок"}], "max_tokens": 2}
                try:
                    async with s.post(f"{base}/chat/completions", json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=20)) as r:
                        body = (await r.text())[:70].replace("\n", " ")
                        print(f"   {scheme:14} {r.status} {body}")
                except Exception as exc:  # noqa: BLE001
                    print(f"   {scheme:14} — {type(exc).__name__}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
