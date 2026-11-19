"""Конфигурация «ПОНЯТНО» — бот, который объясняет домашку, а не списывает её."""
from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

import storage

BASE_DIR = Path(__file__).resolve().parent

# Блокнот умеет сохранять .env в UTF-16 — для python-dotenv это фатальная ошибка
# ещё до запуска бота. Поэтому сначала пробуем штатно, но никогда не падаем.
try:
    load_dotenv(BASE_DIR / ".env")
except Exception:  # noqa: BLE001 — битая кодировка/синтаксис .env
    pass

ENV_ENCODING = "нет файла"


def _parse_env_file() -> dict[str, str]:
    """Ручной разбор .env: UTF-16, BOM, кавычки, лишние пробелы."""
    global ENV_ENCODING
    path = BASE_DIR / ".env"
    if not path.exists():
        return {}
    for encoding in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            text = path.read_text(encoding=encoding)
        except (UnicodeError, LookupError):
            continue
        result: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip().lstrip("\ufeff")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
        if result:
            ENV_ENCODING = encoding
            return result
    return {}


_FILE_ENV = _parse_env_file()


def _bad(value: str | None) -> bool:
    """Признак мусора от неверной кодировки."""
    return not value or not value.strip() or "\x00" in value or "\ufffd" in value


def _setting(name: str, default: str = "") -> str:
    for value in (os.getenv(name), _FILE_ENV.get(name)):
        if not _bad(value):
            return (value or "").strip().strip('"').strip("'")
    return default


BRAND = "ПОНЯТНО"
TAGLINE = "объясню домашку по шагам — чтобы понять, а не списать"

# --- куда писать данные ----------------------------------------------------
# Папка выбирается один раз при старте: проект, иначе LOCALAPPDATA, иначе TEMP.
DATA_DIR, DATA_DIR_NOTE = storage.resolve(BASE_DIR / "data")


def _abs_path(value: str, default_name: str) -> Path:
    """Относительные пути из .env считаем от папки проекта, а не от текущего каталога.

    Иначе `DB_PATH=data/x.sqlite3` при запуске из чужой папки создаёт data/
    где-то в защищённом месте и падает с WinError 5.
    """
    path = Path(value) if value else Path(default_name)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not storage.writable(path.parent):
        return DATA_DIR / path.name
    return path


# --- бот -------------------------------------------------------------------
BOT_TOKEN = _setting("BOT_TOKEN")
DB_PATH = _abs_path(_setting("DB_PATH", ""), "data/ponyatno.sqlite3")
LOG_LEVEL = _setting("LOG_LEVEL", "INFO").upper()
TZ = timezone(timedelta(hours=int(_setting("TZ_OFFSET", "3"))))

# --- AI (любой OpenAI-совместимый провайдер) -------------------------------
AI_BASE_URL = _setting("AI_BASE_URL", "https://api.proxyapi.ru/openai/v1").rstrip("/")
AI_API_KEY = _setting("AI_API_KEY")
AI_MODEL = _setting("AI_MODEL", "gpt-4o-mini")
AI_TIMEOUT = int(_setting("AI_TIMEOUT", "70"))
AI_MAX_TOKENS = int(_setting("AI_MAX_TOKENS", "1200"))
AI_TEMPERATURE = float(_setting("AI_TEMPERATURE", "0.3"))
AI_FORCE_MOCK = _setting("AI_MOCK").lower() in ("1", "true", "yes")
AI_KEYS_STATE = DATA_DIR / "keys_state.json"
ADMIN_ID = int(_setting("ADMIN_ID", "0") or 0)
# несколько админов можно перечислить через запятую
ADMIN_IDS = sorted({int(x) for x in (_setting("ADMIN_IDS", "") or "").split(",") if x.strip().isdigit()} | ({ADMIN_ID} if ADMIN_ID else set()))

# --- лимиты и экономика -----------------------------------------------------
# Каждый день бесплатно начисляется FREE_SOLVES_PER_DAY запросов.
# Сверху можно купить пакет запросов (не сгорают) или подписку — безлимит.
FREE_SOLVES_PER_DAY = int(_setting("FREE_SOLVES_PER_DAY", "3"))
SOLVE_COOLDOWN_SEC = float(_setting("SOLVE_COOLDOWN_SEC", "5"))
MAX_PHOTO_MB = int(_setting("MAX_PHOTO_MB", "6"))
MAX_TEXT_LEN = 1200
XP_PER_SOLVE = 10
XP_LEVEL = 100

# пакеты запросов: ключ -> (сколько запросов, цена в звёздах)
REQUEST_PACKS = {
    "req20": (20, 99),
    "req50": (50, 199),
    "req100": (100, 349),
}

# подписка = безлимит запросов на срок
SUB_PLANS = {
    "sub30": (30, 499, "Подписка · 30 дней"),
    "sub90": (90, 1199, "Подписка · 90 дней"),
}

# --- рефералка и обязательная подписка --------------------------------------
REF_REWARD_REQUESTS = int(_setting("REF_REWARD_REQUESTS", "5"))
CHANNEL_ID = _setting("CHANNEL_ID", "@ponyatno_gdz")
CHANNEL_URL = _setting("CHANNEL_URL", "https://t.me/ponyatno_gdz")
REQUIRE_SUBSCRIPTION = _setting("REQUIRE_SUBSCRIPTION", "1").lower() not in ("0", "false", "no")

# --- экономия на API --------------------------------------------------------
AI_DAILY_CALL_LIMIT = int(_setting("AI_DAILY_CALL_LIMIT", "400"))  # предохранитель
IMAGE_MAX_SIDE = int(_setting("IMAGE_MAX_SIDE", "1024"))           # фото ужимаем перед отправкой
IMAGE_QUALITY = int(_setting("IMAGE_QUALITY", "80"))
ANSWER_CACHE_DAYS = int(_setting("ANSWER_CACHE_DAYS", "14"))

# --- Stars -----------------------------------------------------------------
CURRENCY = "XTR"
DONATION_PACKS = (25, 50, 100, 250)
CUSTOM_DONATE_MIN = 5
CUSTOM_DONATE_MAX = 5000

# --- школа ---------------------------------------------------------------
GRADES = (5, 6, 7, 8, 9, 10, 11)
DEFAULT_GRADE = 8

SUBJECTS = (
    ("math", "Математика", "➗"),
    ("rus", "Русский язык", "📖"),
    ("eng", "Английский", "🅰️"),
    ("phys", "Физика", "⚛️"),
    ("chem", "Химия", "🧪"),
    ("bio", "Биология", "🌿"),
    ("hist", "История", "🏛"),
    ("soc", "Обществознание", "⚖️"),
    ("geo", "География", "🌍"),
    ("inf", "Информатика", "💻"),
    ("lit", "Литература", "📚"),
)
SUBJECT_BY_KEY = {k: (label, emoji) for k, label, emoji in SUBJECTS}
DEFAULT_SUBJECT = "math"


def ai_keys() -> list[str]:
    """Все ключи: AI_API_KEY + список AI_API_KEYS через запятую (без дублей)."""
    raw = [AI_API_KEY] + _setting("AI_API_KEYS").split(",")
    return list(dict.fromkeys(k.strip() for k in raw if k and k.strip()))


def ai_ready() -> bool:
    return bool(ai_keys()) and not AI_FORCE_MOCK
