"""Быстрая проверка первых N ключей напрямую в OpenAI. Только для диагностики."""
from __future__ import annotations

import asyncio
import pathlib
import sys

import aiohttp

KEYS = [l.strip() for l in pathlib.Path("keys.txt").read_text(encoding="utf-8").splitlines()
        if l.strip().startswith("sk-")]
KEYS = list(dict.fromkeys(KEYS))


def mask(k: str) -> str:
    return k[:10] + "…" + k[-4:]


async def call(session, key: str) -> tuple[int, str]:
    payload = {"model": "gpt-4o-mini",
               "messages": [{"role": "user", "content": "ok"}], "max_tokens": 2}
    try:
        async with session.post("https://api.openai.com/v1/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {key}"},
                                timeout=aiohttp.ClientTimeout(total=25)) as r:
            body = await r.text()
            return r.status, body[:100]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


async def main(count: int = 10) -> int:
    print(f"всего ключей: {len(KEYS)}, проверяю {min(count, len(KEYS))}\n")
    async with aiohttp.ClientSession() as s:
        for i, key in enumerate(KEYS[:count], 1):
            status, info = await call(s, key)
            print(f"{i:2}. {mask(key)}  ->  {status or '-'}  {info}")
            await asyncio.sleep(0.4)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)))
