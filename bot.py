"""Точка входа «ПОНЯТНО».

Задачи этого файла: запустить бота и ни при каких условиях не показать
голый трейсбек вместо понятного сообщения.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import sys
import traceback
from pathlib import Path
from typing import NoReturn

MIN_PY = (3, 10)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_FILE = DATA_DIR / "last_error.log"
LOCK_FILE = DATA_DIR / "bot.lock"
log = logging.getLogger("ponyatno")

BAR = "=" * 64


def _prepare_console() -> None:
    """Cyrillic в консоли не должен ломать вывод."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001 — перехваченный поток, перенаправление, pythonw
            pass


def fail(message: str, code: int = 1) -> NoReturn:
    print(f"\n{BAR}\n{message}\n{BAR}")
    if os.name == "nt" and sys.stdin and sys.stdin.isatty() and "--check" not in sys.argv:
        try:
            input("\nНажми Enter, чтобы закрыть окно…")
        except (EOFError, KeyboardInterrupt):
            pass
    raise SystemExit(code)


def _missing_deps() -> list[str]:
    import importlib.util

    return [m for m in ("aiogram", "aiohttp", "dotenv") if importlib.util.find_spec(m) is None]


def preflight() -> None:
    if sys.version_info < MIN_PY:
        fail("Нужен Python 3.10 или новее.\n"
             f"Сейчас запущен {platform.python_version()} ({sys.executable}).\n\n"
             "Поставь свежий Python с python.org и запусти start.bat.")
    missing = _missing_deps()
    if missing:
        fail("Не хватает библиотек: " + ", ".join(missing) + "\n\n"
             f'Поставь их одной командой:\n  "{sys.executable}" -m pip install -r requirements.txt\n\n'
             "Или просто запусти start.bat — он сделает это сам.")


_prepare_console()
preflight()

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import BotCommand, ErrorEvent  # noqa: E402

import ai  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
from handlers import build_router  # noqa: E402
from lock import InstanceLock  # noqa: E402

# папка данных выбирается в config (проект → LOCALAPPDATA → TEMP)
DATA_DIR = config.DATA_DIR
LOG_FILE = DATA_DIR / "last_error.log"
LOCK_FILE = DATA_DIR / "bot.lock"


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def on_error(event: ErrorEvent) -> bool:
    log.exception("Необработанная ошибка: %s", event.exception, exc_info=event.exception)
    return True


async def main() -> None:
    if not config.BOT_TOKEN:
        fail("BOT_TOKEN не задан.\n\nОткрой .env в этой папке и вставь токен от @BotFather.\n"
             "Пример: BOT_TOKEN=123456789:AAH...")

    setup_logging()
    lock = InstanceLock(LOCK_FILE)
    if not lock.acquire():
        fail("Бот уже запущен в другом окне.\n\n"
             "Два экземпляра с одним токеном Telegram не разрешает — второй падает\n"
             "с ошибкой Conflict. Закрой лишнее окно и запусти снова.\n\n"
             "Если окон не видно, сними зависший процесс:\n"
             "  Get-CimInstance Win32_Process | Where-Object Name -match '^python' | "
             "Select-Object ProcessId, CommandLine")

    try:
        db.init()
        log.info("База: %s", config.DB_PATH)

        ai_ok = await ai.healthcheck() if config.ai_keys() else False
        log.info("AI-режим: %s", "включён" if ai_ok else "выключен (офлайн)")
        log.info("Ключи: %s", ai.POOL.report())

        bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher(storage=MemoryStorage())
        dp.errors.register(on_error)
        dp.include_router(build_router())

        try:
            me = await bot.me()
        except TelegramUnauthorizedError:
            await bot.session.close()
            fail("Telegram не принял токен.\n\n"
                 "Проверь .env: возможно, токен отозван или скопирован с ошибкой.\n"
                 "Перевыпустить можно у @BotFather командой /revoke.")
        except Exception as exc:  # noqa: BLE001
            await bot.session.close()
            fail(f"Нет связи с Telegram ({type(exc).__name__}).\n\n"
                 "Проверь интернет, VPN или прокси. Если сеть рабочая — попробуй позже.")

        log.info("Запущен @%s (%s)", me.username, me.id)
        await bot.set_my_commands([
            BotCommand(command="start", description="Начать"),
            BotCommand(command="menu", description="Меню"),
        ])

        # накопившиеся апдейты не выбрасываем: человек нажал /start — должен получить ответ
        await bot.delete_webhook(drop_pending_updates=False)

        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        except TelegramConflictError:
            fail("Telegram уже опрашивает другой экземпляр этого бота.\n\n"
                 "Закрой все лишние окна с ботом и запусти одно.")
        finally:
            await bot.session.close()
    finally:
        db.close()
        lock.release()


# --- диагностика -----------------------------------------------------------
async def diagnose() -> int:
    import aiohttp
    import aiogram
    from aiogram.types import LabeledPrice

    problems = 0

    def line(ok: bool, text: str, hint: str = "") -> None:
        nonlocal problems
        print(("  ✓ " if ok else "  ✗ ") + text)
        if not ok:
            problems += 1
            if hint:
                print("     → " + hint)

    print("\nПОНЯТНО · диагностика запуска")
    print(f"Python {platform.python_version()} · {sys.executable}")
    print(f"Папка проекта: {BASE_DIR}")
    print(f"aiogram {aiogram.__version__} · aiohttp {aiohttp.__version__}\n")

    print("Файлы и настройки:")
    print(f"  · папка данных: {config.DATA_DIR} ({config.DATA_DIR_NOTE})")
    print(f"  · база: {config.DB_PATH}")
    line((BASE_DIR / ".env").exists(), ".env на месте",
         "создай .env из .env.example и вставь токен")
    line(not config._bad(config.BOT_TOKEN),
         f".env читается ({config.ENV_ENCODING})")
    line(bool(re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{25,}", config.BOT_TOKEN or "")),
         "BOT_TOKEN по формату похож на настоящий",
         "токен выглядит как 123456789:AAH... — проверь .env")
    line((BASE_DIR / "requirements.txt").exists(), "requirements.txt на месте")
    try:
        probe = config.DATA_DIR / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        line(True, f"папка данных доступна для записи")
    except Exception as exc:  # noqa: BLE001
        line(False, f"нет доступа к папке данных: {exc}",
             "запусти start.bat или укажи в .env абсолютный DB_PATH")

    if config.BOT_TOKEN:
        print("\nTelegram:")
        bot = Bot(config.BOT_TOKEN)
        try:
            me = await bot.me()
            line(True, f"токен принят: @{me.username} · id={me.id}")
            info = await bot.get_webhook_info()
            line(not info.url, "вебхук не мешает polling",
                 f"сними вебхук: {info.url}")
            try:
                pending = await bot.get_updates(timeout=0)
                line(True, f"getUpdates отвечает (в очереди {len(pending)})")
            except TelegramConflictError:
                line(False, "другой экземпляр бота уже опрашивает Telegram",
                     "закрой лишнее окно с ботом — это единственная причина конфликта")
            try:
                link = await bot.create_invoice_link(
                    title="Проверка Stars", description="Техническая проверка.",
                    payload=f"check:{me.id}", currency=config.CURRENCY,
                    prices=[LabeledPrice(label="Проверка", amount=1)])
                line(bool(link), "оплата звёздами доступна")
            except Exception as exc:  # noqa: BLE001
                line(False, f"Stars недоступны: {type(exc).__name__}: {exc}")
        except TelegramUnauthorizedError:
            line(False, "Telegram не принял токен", "перевыпусти токен у @BotFather (/revoke)")
        except Exception as exc:  # noqa: BLE001
            line(False, f"нет связи с Telegram: {type(exc).__name__}", "проверь интернет/VPN")
        finally:
            await bot.session.close()

    print("\nAI-режим (фото):")
    print(f"  · {ai.POOL.report()}")
    ok_ai = await ai.healthcheck() if config.ai_keys() else False
    if ok_ai:
        line(True, "ключ AI работает — фото включено")
    else:
        st = ai.status()
        if st["state"] == "no_keys":
            print("  · ключей нет — работают математика и алгоритмы (офлайн)")
            print("     → впиши рабочий ключ в .env (AI_API_KEY) и запусти python liveai.py")
        else:
            print(f"  · ключи есть, но не работают: {st['text']}")
            print("     → проверь: python liveai.py (покажет, какой провайдер принимает ключ)")

    print("\n" + BAR)
    if problems:
        print(f"НАЙДЕНО ПРОБЛЕМ: {problems}")
    else:
        print("ВСЁ ГОТОВО К ЗАПУСКУ · запускай start.bat")
    print(BAR)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        try:
            sys.exit(asyncio.run(diagnose()))
        except KeyboardInterrupt:
            sys.exit(130)
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nОстановлено вручную.")
    except TelegramConflictError:
        fail("Telegram уже опрашивает другой экземпляр бота. Закрой лишние окна.")
    except Exception as exc:  # noqa: BLE001
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            LOG_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        fail(f"Бот упал: {type(exc).__name__}: {exc}\n\n"
             f"Подробности записал в файл:\n  {LOG_FILE}\n\n"
             "Пришли этот файл, если нужна помощь.")
