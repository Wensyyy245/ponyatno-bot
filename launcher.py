"""Запуск бота с понятными сообщениями на русском.

start.bat вызывает этот файл, потому что сам .bat cmd читает в OEM-кодировке
и русский текст в нём ломается.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — старые/перехваченные потоки
        pass


def ensure_deps() -> bool:
    try:
        import aiogram  # noqa: F401
        import aiohttp  # noqa: F401
        import dotenv  # noqa: F401
        return True
    except ImportError as exc:
        print(f"Не хватает библиотеки: {exc.name}")
        print("Ставлю зависимости, это займёт минуту…\n")
        req = HERE / "requirements.txt"
        code = subprocess.call([sys.executable, "-m", "pip", "install", "-r", str(req)])
        if code != 0:
            print("\nНе получилось поставить зависимости. Проверь интернет и запусти вручную:")
            print(f'  "{sys.executable}" -m pip install -r requirements.txt')
            return False
        return True


def main() -> int:
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    if not ensure_deps():
        return 1

    import config

    if "--check" not in sys.argv:
        if not config.BOT_TOKEN:
            print("\nBOT_TOKEN пуст. Открой .env и вставь токен от @BotFather.")
            return 1
        print(f"Токен: {config.BOT_TOKEN[:6]}…{config.BOT_TOKEN[-4:]}")
        print(f"AI-ключей в конфиге: {len(config.ai_keys()) or 'нет (офлайн-режим)'}")
        print("\nЗапускаю. Остановить — Ctrl+C.\n")

    import bot

    try:
        if "--check" in sys.argv:
            return asyncio.run(bot.diagnose())
        asyncio.run(bot.main())
    except KeyboardInterrupt:
        print("\nОстановлено вручную.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
