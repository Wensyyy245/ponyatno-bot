"""SQLite-слой «ПОНЯТНО»: пользователи, лимиты, стрики, решения, платежи."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    created_at   TEXT NOT NULL,
    grade        INTEGER,
    subject      TEXT,
    pro_until    TEXT,
    xp           INTEGER NOT NULL DEFAULT 0,
    streak       INTEGER NOT NULL DEFAULT 0,
    last_active  TEXT,
    solves_date  TEXT,
    solves_count INTEGER NOT NULL DEFAULT 0,
    solves_total INTEGER NOT NULL DEFAULT 0,
    requests     INTEGER NOT NULL DEFAULT 0,
    donated      INTEGER NOT NULL DEFAULT 0,
    referred_by  INTEGER,
    ref_bonus_paid INTEGER NOT NULL DEFAULT 0,
    ref_code     TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS solutions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    subject    TEXT,
    grade      INTEGER,
    source     TEXT NOT NULL,
    mode       TEXT NOT NULL,
    provider   TEXT NOT NULL,
    ok         INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    payload    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    stars      INTEGER NOT NULL,
    charge_id  TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sol_user ON solutions(user_id);
CREATE INDEX IF NOT EXISTS idx_pay_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_users_ref ON users(referred_by);
CREATE TABLE IF NOT EXISTS discounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    percent    INTEGER NOT NULL,
    until      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answer_cache (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    provider   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_calls (
    day   TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cache_created ON answer_cache(created_at);"""


def now() -> datetime:
    return datetime.now(config.TZ)


def today() -> str:
    return now().strftime("%Y-%m-%d")


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def init(path=None) -> None:
    global _conn
    db_path = Path(path or config.DB_PATH)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # папка проекта недоступна (запуск из чужого каталога, защищённый путь):
        # уходим в запасную папку данных, а не падаем
        import storage

        fallback, _ = storage.resolve(config.DATA_DIR)
        db_path = Path(fallback) / db_path.name
        db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(SCHEMA)
        _migrate(_conn)
        _conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Добавляет новые колонки в базу, созданную прошлой версией бота."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    for column, definition in (
        ("requests", "INTEGER NOT NULL DEFAULT 0"),
        ("ref_bonus_paid", "INTEGER NOT NULL DEFAULT 0"),
        ("banned", "INTEGER NOT NULL DEFAULT 0"),
        ("grade", "INTEGER"),
        ("subject", "TEXT"),
    ):
        if column not in have:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")



def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.init() не вызван")
    return _conn


def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return _db().execute(sql, params).fetchall()


def q1(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _lock:
        return _db().execute(sql, params).fetchone()


def x(sql: str, params: tuple = ()) -> None:
    with _lock:
        _db().execute(sql, params)
        _db().commit()


# --- пользователи ----------------------------------------------------------
def _ref_code(user_id: int) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    n = (user_id * 2654435761) % (36 ** 6)
    out = ""
    for _ in range(6):
        n, r = divmod(n, len(alphabet))
        out += alphabet[r]
    return out


def ensure_user(user_id: int, username: str | None, first_name: str | None,
                referred_by: int | None = None) -> sqlite3.Row:
    row = get_user(user_id)
    if row is not None:
        x("UPDATE users SET username=?, first_name=? WHERE user_id=?",
          ((username or "")[:64], (first_name or "")[:64], user_id))
        return get_user(user_id)  # type: ignore[return-value]
    code = _ref_code(user_id)
    while q1("SELECT 1 FROM users WHERE ref_code=?", (code,)):
        code = _ref_code(user_id + len(code))
    x("INSERT INTO users (user_id, username, first_name, created_at, ref_code, last_active, streak, grade, subject) "
      "VALUES (?,?,?,?,?,?,1,?,?)",
      (user_id, (username or "")[:64], (first_name or "")[:64], iso(now()), code, today(),
       config.DEFAULT_GRADE, config.DEFAULT_SUBJECT))
    if referred_by and referred_by != user_id and get_user(referred_by) is not None:
        # бонус начисляется не сразу, а после подписки на канал (см. handlers/common.py)
        x("UPDATE users SET referred_by=? WHERE user_id=?", (referred_by, user_id))
    return get_user(user_id)  # type: ignore[return-value]


def count_pending_refs(user_id: int) -> int:
    """Друзья, которые пришли, но ещё не подтвердили подписку."""
    row = q1("SELECT COUNT(*) AS c FROM users WHERE referred_by=? AND ref_bonus_paid=0", (user_id,))
    return row["c"] if row else 0


def get_user(user_id: int) -> sqlite3.Row | None:
    return q1("SELECT * FROM users WHERE user_id=?", (user_id,))


def get_by_ref(code: str) -> sqlite3.Row | None:
    return q1("SELECT * FROM users WHERE ref_code=?", (code,))


def set_grade(user_id: int, grade: int) -> None:
    x("UPDATE users SET grade=? WHERE user_id=?", (grade, user_id))


def set_subject(user_id: int, subject: str) -> None:
    x("UPDATE users SET subject=? WHERE user_id=?", (subject, user_id))


def is_pro(row: sqlite3.Row) -> bool:
    return bool(row["pro_until"]) and row["pro_until"] > iso(now())


def pro_days_left(row: sqlite3.Row) -> int:
    if not row["pro_until"]:
        return 0
    try:
        until = datetime.strptime(row["pro_until"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=config.TZ)
    except ValueError:
        return 0
    left = (until - now()).total_seconds()
    return max(0, int(left // 86400) + (1 if left % 86400 else 0))


def grant_pro_days(user_id: int, days: int) -> None:
    row = get_user(user_id)
    if row is None:
        return
    base = now()
    if row["pro_until"]:
        try:
            cand = datetime.strptime(row["pro_until"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=config.TZ)
            if cand > base:
                base = cand
        except ValueError:
            pass
    x("UPDATE users SET pro_until=? WHERE user_id=?", (iso(base + timedelta(days=days)), user_id))


# --- активность и лимиты ---------------------------------------------------
def touch(user_id: int) -> None:
    row = get_user(user_id)
    if row is None:
        return
    t = today()
    if row["last_active"] == t:
        return
    y = (now() - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = (row["streak"] or 0) + 1 if row["last_active"] == y else 1
    x("UPDATE users SET last_active=?, streak=? WHERE user_id=?", (t, streak, user_id))


def daily_free_left(row: sqlite3.Row) -> int:
    """Сколько бесплатных запросов осталось на сегодня."""
    used = row["solves_count"] if row["solves_date"] == today() else 0
    return max(0, config.FREE_SOLVES_PER_DAY - used)


def requests_left(row: sqlite3.Row) -> int:
    """Купленные и бонусные запросы — не сгорают."""
    return max(0, row["requests"] or 0)


def solves_left(row: sqlite3.Row) -> int | None:
    """Доступно запросов. None — подписка, то есть безлимит."""
    if is_pro(row):
        return None
    return daily_free_left(row) + requests_left(row)


def is_unlimited(row: sqlite3.Row) -> bool:
    return is_pro(row)


def use_solve(user_id: int) -> None:
    """Списывает сначала бесплатные дневные, потом купленные запросы."""
    row = get_user(user_id)
    if row is None:
        return
    t = today()
    if not is_pro(row) and daily_free_left(row) > 0:
        x("UPDATE users SET solves_count = CASE WHEN solves_date=? THEN solves_count + 1 ELSE 1 END, "
          "solves_date=?, solves_total = solves_total + 1 WHERE user_id=?", (t, t, user_id))
        return
    if not is_pro(row):
        x("UPDATE users SET requests = MAX(requests - 1, 0) WHERE user_id=?", (user_id,))
    x("UPDATE users SET solves_total = solves_total + 1 WHERE user_id=?", (user_id,))


def add_requests(user_id: int, count: int) -> int:
    """Начисляет запросы (покупка или бонус). Возвращает новый баланс."""
    x("UPDATE users SET requests = requests + ? WHERE user_id=?", (count, user_id))
    row = get_user(user_id)
    return row["requests"] if row else count


def grant_subscription(user_id: int, days: int) -> None:
    grant_pro_days(user_id, days)


def mark_ref_bonus(user_id: int) -> None:
    x("UPDATE users SET ref_bonus_paid=1 WHERE user_id=?", (user_id,))


def ref_bonus_paid(row: sqlite3.Row) -> bool:
    return bool(row["ref_bonus_paid"])


def add_xp(user_id: int, amount: int) -> tuple[int, int]:
    x("UPDATE users SET xp = xp + ? WHERE user_id=?", (amount, user_id))
    row = get_user(user_id)
    xp = row["xp"] if row else 0
    return xp, xp // config.XP_LEVEL + 1


def log_solution(user_id: int, subject: str | None, grade: int | None,
                 source: str, mode: str, provider: str, ok: bool = True) -> None:
    x("INSERT INTO solutions (user_id, subject, grade, source, mode, provider, ok, created_at) "
      "VALUES (?,?,?,?,?,?,?,?)",
      (user_id, subject, grade, source, mode, provider, int(ok), iso(now())))


def count_solutions(user_id: int) -> int:
    row = q1("SELECT COUNT(*) AS c FROM solutions WHERE user_id=? AND ok=1", (user_id,))
    return row["c"] if row else 0


# --- платежи ---------------------------------------------------------------
def add_payment(user_id: int, payload: str, kind: str, stars: int, charge_id: str | None) -> None:
    x("INSERT INTO payments (user_id, payload, kind, stars, charge_id, created_at) VALUES (?,?,?,?,?,?)",
      (user_id, payload, kind, stars, charge_id, iso(now())))


def add_donation(user_id: int, stars: int) -> int:
    x("UPDATE users SET donated = donated + ? WHERE user_id=?", (stars, user_id))
    row = get_user(user_id)
    return row["donated"] if row else stars


def has_charge(charge_id: str) -> bool:
    return q1("SELECT 1 FROM payments WHERE charge_id=?", (charge_id,)) is not None


def count_refs(user_id: int) -> int:
    row = q1("SELECT COUNT(*) AS c FROM users WHERE referred_by=?", (user_id,))
    return row["c"] if row else 0


def stats() -> dict:
    row = q1(
        "SELECT (SELECT COUNT(*) FROM users) AS users, "
        "(SELECT COUNT(*) FROM solutions WHERE ok=1) AS solves, "
        "(SELECT COALESCE(SUM(stars),0) FROM payments) AS stars, "
        "(SELECT COALESCE(SUM(CASE WHEN pro_until > ? THEN 1 ELSE 0 END),0) FROM users) AS pro",
        (iso(now()),),
    )
    return dict(row) if row else {"users": 0, "solves": 0, "stars": 0, "pro": 0}


# --- кэш ответов и учёт вызовов AI -----------------------------------------
def cache_get(key: str) -> sqlite3.Row | None:
    return q1("SELECT payload, provider FROM answer_cache WHERE key=?", (key,))


def cache_put(key: str, payload: str, provider: str) -> None:
    x("INSERT OR REPLACE INTO answer_cache (key, payload, provider, created_at) VALUES (?,?,?,?)",
      (key, payload, provider, iso(now())))


def cache_gc(days: int) -> int:
    """Чистит старые записи кэша, чтобы база не пухла."""
    cut = iso(now() - timedelta(days=days))
    row = q1("SELECT COUNT(*) AS c FROM answer_cache WHERE created_at < ?", (cut,))
    x("DELETE FROM answer_cache WHERE created_at < ?", (cut,))
    return row["c"] if row else 0


def ai_calls_today() -> int:
    row = q1("SELECT count FROM ai_calls WHERE day=?", (today(),))
    return row["count"] if row else 0


def ai_call_bump() -> int:
    t = today()
    x("INSERT INTO ai_calls (day, count) VALUES (?, 1) "
      "ON CONFLICT(day) DO UPDATE SET count = count + 1", (t,))
    return ai_calls_today()

# --- админка: блокировки, скидки, статистика -------------------------------
def set_banned(user_id: int, flag: bool) -> None:
    x("UPDATE users SET banned=? WHERE user_id=?", (int(flag), user_id))


def is_banned(row: sqlite3.Row) -> bool:
    return bool(row["banned"])


def find_user(query: str) -> sqlite3.Row | None:
    query = (query or "").strip().lstrip("@")
    if not query:
        return None
    if query.isdigit():
        return q1("SELECT * FROM users WHERE user_id=?", (int(query),))
    return q1("SELECT * FROM users WHERE lower(username)=lower(?)", (query,))


def recent_payments(limit: int = 10) -> list[sqlite3.Row]:
    return q("SELECT * FROM payments ORDER BY id DESC LIMIT ?", (limit,))


def all_user_ids(include_banned: bool = False) -> list[int]:
    sql = "SELECT user_id FROM users" + ("" if include_banned else " WHERE banned=0")
    return [row["user_id"] for row in q(sql)]


def add_discount(percent: int, hours: float) -> None:
    until = iso(now() + timedelta(hours=hours))
    x("INSERT INTO discounts (percent, until, created_at) VALUES (?,?,?)",
      (max(1, min(90, int(percent))), until, iso(now())))


def active_discount() -> sqlite3.Row | None:
    return q1("SELECT * FROM discounts WHERE until > ? ORDER BY percent DESC LIMIT 1",
              (iso(now()),))


def discounts_list(limit: int = 10) -> list[sqlite3.Row]:
    return q("SELECT * FROM discounts ORDER BY id DESC LIMIT ?", (limit,))


def clear_discounts() -> int:
    row = q1("SELECT COUNT(*) AS c FROM discounts WHERE until > ?", (iso(now()),))
    x("DELETE FROM discounts")
    return row["c"] if row else 0


def admin_stats() -> dict:
    t = today()
    row = q1(
        "SELECT (SELECT COUNT(*) FROM users) AS users, "
        "(SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)=?) AS new_today, "
        "(SELECT COUNT(*) FROM users WHERE last_active=?) AS active_today, "
        "(SELECT COALESCE(SUM(solves_total),0) FROM users) AS solves_total, "
        "(SELECT COUNT(*) FROM solutions WHERE substr(created_at,1,10)=?) AS solves_today, "
        "(SELECT COUNT(*) FROM users WHERE pro_until > ?) AS pro, "
        "(SELECT COUNT(*) FROM users WHERE banned=1) AS banned, "
        "(SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL) AS refs, "
        "(SELECT COALESCE(SUM(requests),0) FROM users) AS requests_pool, "
        "(SELECT COALESCE(SUM(stars),0) FROM payments) AS stars, "
        "(SELECT COUNT(*) FROM payments) AS payments, "
        "(SELECT COUNT(*) FROM answer_cache) AS cache",
        (t, t, t, iso(now())),
    )
    data = dict(row) if row else {}
    data["ai_today"] = ai_calls_today()
    data["ai_limit"] = config.AI_DAILY_CALL_LIMIT
    return data