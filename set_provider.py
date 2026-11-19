"""Подключение любого OpenAI-совместимого провайдера одной командой.

Пример:
    python set_provider.py https://api.пример.ру/v1 gpt-4o-mini sk-ключ

Что делает:
1. прописывает AI_BASE_URL, AI_MODEL, AI_API_KEY в .env;
2. сразу проверяет ключ настоящим запросом к модели;
3. сбрасывает карантин ключей, чтобы бот взял новый сразу.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import aiohttp

ENV_FILE = Path(__file__).resolve().parent / ".env"
STATE = Path(__file__).resolve().parent / "data" / "keys_state.json"


def mask(key: str) -> str:
    return f"{key[:10]}…{key[-4:]}" if len(key) > 16 else key


def write_env(base: str, model: str, key: str) -> None:
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    for name, value in (("AI_BASE_URL", base), ("AI_MODEL", model), ("AI_API_KEY", key),
                        ("AI_API_KEYS", "")):
        line = f"{name}={value}"
        if re.search(rf"^{name}=.*$", text, flags=re.MULTILINE):
            text = re.sub(rf"^{name}=.*$", line, text, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
    ENV_FILE.write_text(text, encoding="utf-8")
    STATE.unlink(missing_ok=True)


async def probe(base: str, model: str, key: str) -> tuple[bool, str, list[str]]:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    models: list[str] = []
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(f"{base}/models", headers=headers,
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    data = await r.json()
                    models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
        except Exception:  # noqa: BLE001
            pass

        payload = {"model": model, "messages": [{"role": "user", "content": "Ответь одним словом: работает"}],
                   "max_tokens": 10}
        try:
            async with s.post(f"{base}/chat/completions", json=payload, headers=headers,
                              timeout=aiohttp.ClientTimeout(total=40)) as r:
                body = await r.text()
                if r.status == 200:
                    data = json.loads(body)
                    text = data["choices"][0]["message"]["content"]
                    return True, f"модель ответила: {str(text).strip()[:60]}", models
                return False, f"HTTP {r.status}: {body[:160]}", models
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}", models


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    base = sys.argv[1].rstrip("/")
    model = sys.argv[2]
    key = sys.argv[3].strip()
    print(f"адрес: {base}\nмодель: {model}\nключ: {mask(key)}\n")

    ok, info, models = asyncio.run(probe(base, model, key))
    print(("✓ " if ok else "✗ ") + info)
    if models:
        print(f"  доступно моделей: {len(models)} · например: {', '.join(models[:5])}")
        if model not in models:
            print(f"  ! модели {model} в списке нет — возможно, нужно другое имя")
    if not ok:
        print("\nКлюч/адрес не подтверждены, .env не менял.")
        print("Проверь: правильный ли base_url, есть ли /v1 в пути, то ли имя модели.")
        return 1

    write_env(base, model, key)
    print("\n.env обновлён, карантин ключей сброшен. Перезапусти бота — фото включится.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
