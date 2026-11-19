"""Живой smoke-тест: токен бота, вебхук, Stars-счёт, состояние пула ключей.

Ничего не отправляет в чаты. Запуск:  python smoke.py
"""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import LabeledPrice

import ai
import config

EXPECTED_LANDING_USERNAME = "saasiitest_bot"


async def main() -> int:
    if not config.BOT_TOKEN:
        print("✗ BOT_TOKEN пуст в .env")
        return 1
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    problems = 0
    try:
        me = await bot.me()
        print(f"✓ токен валиден: @{me.username} · {me.first_name} · id={me.id}")
        if me.username != EXPECTED_LANDING_USERNAME:
            print(f"! username @{me.username} не совпадает с лендингом "
                  f"(@{EXPECTED_LANDING_USERNAME}) — поправь landing/index.html")

        info = await bot.get_webhook_info()
        print("✗ вебхук включён, polling не заработает" if info.url else "✓ вебхук не мешает polling")
        problems += bool(info.url)

        updates = await bot.get_updates(offset=-1, timeout=0)
        print(f"✓ getUpdates отвечает (в очереди {len(updates)})")

        try:
            link = await bot.create_invoice_link(
                title="Проверка Stars",
                description="Техническая проверка, оплачивать не нужно.",
                payload=f"check:{me.id}",
                currency=config.CURRENCY,
                prices=[LabeledPrice(label="Проверка", amount=1)],
            )
            print(f"✓ Stars-счёт создаётся: {link[:52]}…")
        except Exception as exc:  # noqa: BLE001
            print(f"✗ Stars-счёт не создаётся: {type(exc).__name__}: {exc}")
            problems += 1
    except TelegramUnauthorizedError:
        print("✗ токен недействителен — перевыпусти в @BotFather")
        problems += 1
    except Exception as exc:  # noqa: BLE001
        print(f"✗ сеть/Telegram: {type(exc).__name__}: {exc}")
        problems += 1
    finally:
        await bot.session.close()

    await ai.healthcheck()
    print(f"\nПул ключей AI: {ai.POOL.report()}")
    print(f"Режим: {'AI (фото включено)' if ai.ready() else 'офлайн (фото выключено)'}")
    if not ai.ready():
        print("  → это не ошибка: математика и алгоритмы работают без ключа")

    print("\n" + ("ВСЁ ЧИСТО" if problems == 0 else f"ПРОБЛЕМ: {problems}"))
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
