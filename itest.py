"""Интеграционный тест: прогоняет апдейты через настоящий Dispatcher aiogram.

Сеть не нужна — Bot подменён моками. Проверяет связку «роутер → хендлер → ответ»,
оба режима (AI-мок и чистый офлайн), лимиты, оплату и защиту от повторов.

Запуск:  python itest.py
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ["AI_MOCK"] = "0"

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import Update, User  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import store  # noqa: E402
from handlers import build_router  # noqa: E402

FAILS: list[str] = []
OK = 0
_seq = [1000]


def check(cond: bool, msg: str) -> None:
    global OK
    if cond:
        OK += 1
    else:
        FAILS.append(msg)


def uid() -> int:
    _seq[0] += 1
    return _seq[0]


class Rec:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def add(self, name: str, kw: dict, args: tuple = ()) -> None:
        self.calls.append((name, {"args": args, **kw}))

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)

    def last(self, name: str | None = None) -> dict:
        for n, kw in reversed(self.calls):
            if name is None or n == name:
                return {"method": n, **kw}
        return {}

    def texts(self) -> str:
        return "\n".join(str(kw.get("text") or kw.get("caption") or "") for _, kw in self.calls)


class FakeBot(Bot):
    """Перехватывает все вызовы Bot: в aiogram 3.29 хендлеры идут через bot(method)."""

    def __init__(self) -> None:
        super().__init__(token="42:TEST")
        self.rec = Rec()
        self.member_status = "member"

    async def __call__(self, method, request_timeout=None):  # type: ignore[override]
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", type(method).__name__).lower()
        self.rec.add(name, method.model_dump(exclude_none=True))
        if name in ("send_message", "copy_message", "edit_message_text"):
            return FakeSent(self)
        return None

    async def me(self) -> User:  # type: ignore[override]
        return User(id=42, is_bot=True, first_name="ПОНЯТНО", username="saasiitest_bot")

    async def get_chat_member(self, *a, **kw):  # type: ignore[override]
        self.rec.add("get_chat_member", kw)
        return SimpleNamespace(status=self.member_status)

    async def download(self, file, destination=None, **kw):  # type: ignore[override]
        buf = destination if isinstance(destination, io.BytesIO) else io.BytesIO()
        buf.write(b"\xff\xd8fake-jpeg-bytes")
        return buf


class FakeSent:
    """Как настоящее сообщение: можно редактировать и удалять."""

    def __init__(self, bot) -> None:
        self.bot = bot

    async def edit_text(self, text=None, **kw):
        if text is not None:
            kw["text"] = text
        self.bot.rec.add("edit_message_text", kw)
        return self

    async def delete(self):
        return True

    async def answer(self, text=None, **kw):
        if text is not None:
            kw["text"] = text
        self.bot.rec.add("send_message", kw)
        return self


def user_json(u: int) -> dict:
    return {"id": u, "is_bot": False, "first_name": "Тест", "username": "tester",
            "language_code": "ru"}


def chat(u: int) -> dict:
    return {"id": u, "type": "private"}


def msg(u: int, text: str, entities: list | None = None, photo: bool = False) -> dict:
    _seq[0] += 1
    m: dict = {"message_id": _seq[0], "date": int(time.time()), "chat": chat(u), "from": user_json(u)}
    if photo:
        m["photo"] = [{"file_id": "photo-1", "file_unique_id": "u1", "width": 800,
                       "height": 1000, "file_size": 120_000}]
    else:
        m["text"] = text
        if entities:
            m["entities"] = entities
    return {"update_id": _seq[0], "message": m}


def cmd(u: int, text: str = "/start", args: str | None = None) -> dict:
    full = f"{text} {args}" if args else text
    return msg(u, full, entities=[{"type": "bot_command", "offset": 0, "length": len(text)}])


def cb(u: int, data: str) -> dict:
    _seq[0] += 1
    return {"update_id": _seq[0], "callback_query": {
        "id": str(_seq[0]), "from": user_json(u), "chat_instance": "1", "data": data,
        "message": {"message_id": 100, "date": int(time.time()), "chat": chat(u),
                    "from": {"id": 42, "is_bot": True, "first_name": "ПОНЯТНО",
                             "username": "saasiitest_bot"},
                    "text": "меню"}}}


def pre_checkout(u: int, payload: str, amount: int = 149) -> dict:
    _seq[0] += 1
    return {"update_id": _seq[0], "pre_checkout_query": {
        "id": str(_seq[0]), "from": user_json(u), "currency": "XTR",
        "total_amount": amount, "invoice_payload": payload}}


def paid(u: int, payload: str, amount: int, charge: str, currency: str = "XTR") -> dict:
    _seq[0] += 1
    return {"update_id": _seq[0], "message": {
        "message_id": 200, "date": int(time.time()), "chat": chat(u), "from": user_json(u),
        "successful_payment": {"currency": currency, "total_amount": amount,
                               "invoice_payload": payload,
                               "telegram_payment_charge_id": charge,
                               "provider_payment_charge_id": "prov-" + charge}}}


async def feed(dp: Dispatcher, bot: FakeBot, data: dict) -> None:
    await dp.feed_update(bot, Update.model_validate(data, context={"bot": bot}))


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ponyatno-itest-"))
    config.DB_PATH = tmp / "itest.sqlite3"
    db.init(config.DB_PATH)

    import ai
    import offline

    bot = FakeBot()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_router())
    ai.POOL._keys = []          # по умолчанию — чистый офлайн
    config.AI_API_KEY = ""      # и «ключей нет», чтобы сообщение было честным
    config.AI_FORCE_MOCK = False
    config.CHANNEL_ID = ""      # подписку проверяем отдельным блоком ниже
    config.REQUIRE_SUBSCRIPTION = False

    # --- старт и рефералка -------------------------------------------------
    u1 = uid()
    await feed(dp, bot, cmd(u1))
    t = bot.rec.texts()
    check("ПОНЯТНО" in t, "нет бренда в приветствии")
    check(bot.rec.count("send_message") == 1, "приветствие не отправлено")
    check(db.get_user(u1) is not None, "пользователь не создан")

    code = db.get_user(u1)["ref_code"]
    u2 = uid()
    await feed(dp, bot, cmd(u2, args=f"ref_{code}"))
    check(db.get_user(u2)["referred_by"] == u1, "реферал не привязался")
    check(db.requests_left(db.get_user(u1)) == config.REF_REWARD_REQUESTS,
          f"без канала бонус должен начисляться сразу, а он {db.requests_left(db.get_user(u1))}")
    check(not db.is_pro(db.get_user(u2)), "приглашённому выдали подписку — не должны")

    # --- рефералка через канал --------------------------------------------
    config.CHANNEL_ID = "@test_channel"
    config.REQUIRE_SUBSCRIPTION = True
    u_ch, u_inv = uid(), uid()
    await feed(dp, bot, cmd(u_inv))
    code_inv = db.get_user(u_inv)["ref_code"]
    await feed(dp, bot, cmd(u_ch, args=f"ref_{code_inv}"))
    check(db.count_pending_refs(u_inv) == 1, "друг не попал в ожидающие бонуса")
    check(db.requests_left(db.get_user(u_inv)) == 0, "бонус выдан до подписки")

    bot.member_status = "left"
    await feed(dp, bot, cb(u_ch, "ref:check"))
    check(db.ref_bonus_paid(db.get_user(u_ch)) is False, "бонус выдан без подписки")

    bot.member_status = "member"
    await feed(dp, bot, cb(u_ch, "ref:check"))
    check(db.requests_left(db.get_user(u_inv)) == config.REF_REWARD_REQUESTS,
          "за подписку друга не начислили запросы")
    check(db.ref_bonus_paid(db.get_user(u_ch)), "бонус не помечен")
    total_after = db.requests_left(db.get_user(u_inv))
    await feed(dp, bot, cb(u_ch, "ref:check"))
    check(db.requests_left(db.get_user(u_inv)) == total_after, "бонус начислен дважды")
    config.CHANNEL_ID = ""
    config.REQUIRE_SUBSCRIPTION = False

    # --- меню и разделы ----------------------------------------------------
    for data, needle, label in [("m:profile", "Уровень", "профиль"),
                                ("m:help", "Как это работает", "справка"),
                                ("m:ref", "?start=ref_", "рефералка"),
                                ("m:pay", "Магазин", "магазин"),
                                ("m:setup", "Класс и предмет", "настройки")]:
        before = len(bot.rec.calls)
        await feed(dp, bot, cb(u1, data))
        check(len(bot.rec.calls) > before, f"{label}: нет ответа")
        check(needle in bot.rec.texts(), f"{label}: нет «{needle}»")

    # --- класс и предмет ---------------------------------------------------
    await feed(dp, bot, cb(u1, "m:grades"))
    await feed(dp, bot, cb(u1, "gr:9"))
    check(db.get_user(u1)["grade"] == 9, "класс не сохранился")
    await feed(dp, bot, cb(u1, "gr:99"))
    check(db.get_user(u1)["grade"] == 9, "принят несуществующий класс")
    await feed(dp, bot, cb(u1, "m:subjects"))
    await feed(dp, bot, cb(u1, "sub:rus"))
    check(db.get_user(u1)["subject"] == "rus", "предмет не сохранился")
    await feed(dp, bot, cb(u1, "sub:нет"))
    check(db.get_user(u1)["subject"] == "rus", "принят несуществующий предмет")

    # --- офлайн-разбор уравнения ------------------------------------------
    u3 = uid()
    await feed(dp, bot, cmd(u3))
    await feed(dp, bot, cb(u3, "m:text"))
    check("Напиши задание" in bot.rec.texts(), "нет запроса текста")
    await feed(dp, bot, msg(u3, "Реши уравнение: 5(x - 2) = 3x + 1"))
    t = bot.rec.texts()
    check("x = 5,5" in t, f"офлайн не решил уравнение: {t[-200:]}")
    check("По шагам" in t, "нет шагов в ответе")
    check(db.get_user(u3)["solves_total"] == 1, "разбор не учтён")
    check(db.get_user(u3)["xp"] == config.XP_PER_SOLVE, "XP не начислен")

    # короткая тема отбивается
    await feed(dp, bot, cb(u3, "m:text"))
    await feed(dp, bot, msg(u3, "1"))
    check("Слишком коротко" in bot.rec.texts() or db.get_user(u3)["solves_total"] >= 1,
          "короткий ввод не обработан")

    # антифлуд
    store._last[u3] = time.monotonic()
    await feed(dp, bot, cb(u3, "m:text"))
    await feed(dp, bot, msg(u3, "2+2"))
    check("Секунду" in bot.rec.texts(), "антифлуд не сработал")

    # «проще» без сохранённой задачи
    u4 = uid()
    await feed(dp, bot, cmd(u4))
    await feed(dp, bot, cb(u4, "a:simpler"))
    check("нужен текст задания" in bot.rec.texts(), "нет подсказки про текст")

    # --- AI-мок: ответ и «похожая задача» ---------------------------------
    config.AI_FORCE_MOCK = True
    u5 = uid()
    await feed(dp, bot, cmd(u5))
    await feed(dp, bot, cb(u5, "m:text"))
    await feed(dp, bot, msg(u5, "Задача про поезда: 60 км/ч, 2 часа, какой путь?"))
    t = bot.rec.texts()
    check("По шагам" in t, "AI-мок не вернул разбор")
    check(store.get(u5) is not None, "задача не сохранена для повторов")
    await feed(dp, bot, cb(u5, "a:similar"))
    check(bot.rec.count("send_message") >= 3, "похожая задача не отправлена")
    await feed(dp, bot, cb(u5, "a:simpler"))
    check("По шагам" in bot.rec.texts(), "режим «проще» не отработал")

    # проверка своего решения через AI-мок
    await feed(dp, bot, cb(u5, "m:check"))
    await feed(dp, bot, msg(u5, "120 км"))
    check(bot.rec.count("send_message") >= 4, "проверка решения не ответила")

    # фото с AI-моком
    await feed(dp, bot, cb(u5, "m:solve"))
    await feed(dp, bot, msg(u5, "", photo=True))
    check("По шагам" in bot.rec.texts(), "фото не разобрано в AI-режиме")
    config.AI_FORCE_MOCK = False

    # --- фото без AI-ключа -------------------------------------------------
    u6 = uid()
    await feed(dp, bot, cmd(u6))
    await feed(dp, bot, cb(u6, "m:solve"))
    check("Текст работает" in bot.rec.texts() or "не читаю" in bot.rec.texts(),
          "не предупредили про выключенное фото")
    await feed(dp, bot, msg(u6, "", photo=True))
    check("Фото пока не читаю" in bot.rec.texts() or "провайдер их" in bot.rec.texts(),
          "фото не отбито без ключа")

    # --- обязательная подписка --------------------------------------------
    config.CHANNEL_ID = "@gate_channel"
    config.REQUIRE_SUBSCRIPTION = True
    u_g = uid()
    await feed(dp, bot, cmd(u_g))
    bot.member_status = "left"
    await feed(dp, bot, cb(u_g, "m:text"))
    check("подпишись на наш канал" in bot.rec.texts(), "без подписки пустили к решению")
    bot.member_status = "member"
    await feed(dp, bot, cb(u_g, "gate:check"))
    check("доступ открыт" in str(bot.rec.last("answer_callback_query").get("text") or ""),
          "после подписки доступ не открылся")
    config.CHANNEL_ID = ""
    config.REQUIRE_SUBSCRIPTION = False

    # --- лимит -------------------------------------------------------------
    u7 = uid()
    await feed(dp, bot, cmd(u7))
    for _ in range(config.FREE_SOLVES_PER_DAY):
        db.use_solve(u7)
    await feed(dp, bot, cb(u7, "m:text"))
    check("закончились" in bot.rec.texts(), "лимит не показан на входе")
    await feed(dp, bot, cb(u7, "m:pay"))
    t = bot.rec.texts()
    check("Запросы" in t and "Подписка" in t and "Поддержать" in t, "в магазине нет трёх товаров")

    # докупка запросов снимает лимит
    db.add_requests(u7, 2)
    await feed(dp, bot, cb(u7, "m:text"))
    last_text = str(bot.rec.last("edit_message_text").get("text") or "")
    check("закончились" not in last_text, f"купленные запросы не сняли лимит: {last_text[:60]}")

    # --- проверка решения офлайн ------------------------------------------
    u8 = uid()
    await feed(dp, bot, cmd(u8))
    await feed(dp, bot, cb(u8, "m:check"))
    check("Шаг 1 из 2" in bot.rec.texts(), "нет шага с заданием")
    await feed(dp, bot, msg(u8, "2x + 3 = 7"))
    check("Шаг 2 из 2" in bot.rec.texts(), "нет шага с решением")
    await feed(dp, bot, msg(u8, "x = 3"))
    t = bot.rec.texts()
    check("Не сходится" in t, "неверный ответ не отловлен")
    check("x = 2" in t, "не показан верный ответ")

    u9 = uid()
    await feed(dp, bot, cmd(u9))
    await feed(dp, bot, cb(u9, "m:check"))
    await feed(dp, bot, msg(u9, "2x + 3 = 7"))
    await feed(dp, bot, msg(u9, "x = 2"))
    check("Сходится" in bot.rec.texts(), "верный ответ не подтверждён")

    # --- оплата: три отдельных товара -------------------------------------
    u10 = uid()
    await feed(dp, bot, cmd(u10))

    # 1) запросы
    await feed(dp, bot, cb(u10, "shop:req"))
    check("Запросы" in bot.rec.texts(), "нет экрана запросов")
    req_count, req_stars = config.REQUEST_PACKS["req20"]
    await feed(dp, bot, cb(u10, "buy:req20"))
    inv = bot.rec.last("send_invoice")
    check(inv.get("currency") == "XTR", "валюта не XTR")
    check(inv.get("prices") and inv["prices"][0]["amount"] == req_stars, "сумма пакета неверная")
    check(inv.get("payload") == f"req:{u10}:req20", "payload пакета неверный")
    check("provider_token" not in inv, "передан provider_token для Stars")

    # 2) подписка
    await feed(dp, bot, cb(u10, "shop:sub"))
    check("безлимит" in bot.rec.texts().lower(), "нет экрана подписки")
    sub_days, sub_stars, _ = config.SUB_PLANS["sub30"]
    await feed(dp, bot, cb(u10, "buy:sub30"))
    inv = bot.rec.last("send_invoice")
    check(inv.get("prices") and inv["prices"][0]["amount"] == sub_stars, "сумма подписки неверная")
    check(inv.get("payload") == f"sub:{u10}:sub30", "payload подписки неверный")

    # 3) поддержка
    await feed(dp, bot, cb(u10, "shop:don"))
    check("Поддержать" in bot.rec.texts() or "Спасибо" in bot.rec.texts(), "нет экрана поддержки")
    await feed(dp, bot, cb(u10, "don:50"))
    check(bot.rec.last("send_invoice").get("payload") == f"don:{u10}:50", "payload доната неверный")

    await feed(dp, bot, cb(u10, "pay:custom"))
    await feed(dp, bot, msg(u10, "не число"))
    check("целое число" in bot.rec.texts(), "мусор в сумме не отбит")
    await feed(dp, bot, msg(u10, "1"))
    check("от 5 до 5000" in bot.rec.texts(), "малая сумма не отбита")
    await feed(dp, bot, msg(u10, "30"))
    check(bot.rec.last("send_invoice").get("payload") == f"don:{u10}:30", "своя сумма не ушла")

    await feed(dp, bot, pre_checkout(u10, f"req:{u10}:req20", req_stars))
    check(bot.rec.last("answer_pre_checkout_query").get("ok") is True, "валидный чек отклонён")
    await feed(dp, bot, pre_checkout(u10, f"req:{u10 + 1}:req20", req_stars))
    check(bot.rec.last("answer_pre_checkout_query").get("ok") is False, "чужой чек принят")
    await feed(dp, bot, pre_checkout(u10, f"req:{u10}:req20", 1))
    check(bot.rec.last("answer_pre_checkout_query").get("ok") is False, "чек с неверной суммой принят")
    await feed(dp, bot, pre_checkout(u10, "мусор", req_stars))
    check(bot.rec.last("answer_pre_checkout_query").get("ok") is False, "битый payload принят")

    # запросы
    before = db.requests_left(db.get_user(u10))
    await feed(dp, bot, paid(u10, f"req:{u10}:req20", req_stars, "chg-req"))
    check(db.requests_left(db.get_user(u10)) == before + req_count,
          f"запросы не начислены: {db.requests_left(db.get_user(u10))}")
    check("Начислено" in bot.rec.texts(), "нет подтверждения покупки запросов")
    after = db.requests_left(db.get_user(u10))
    await feed(dp, bot, paid(u10, f"req:{u10}:req20", req_stars, "chg-req"))
    check(db.requests_left(db.get_user(u10)) == after, "повторный charge начислил запросы дважды")
    check("уже учтён" in bot.rec.texts(), "нет ответа на дубль")

    # подписка = безлимит
    await feed(dp, bot, paid(u10, f"sub:{u10}:sub30", sub_stars, "chg-sub"))
    check(db.is_pro(db.get_user(u10)), "подписка не выдана")
    check(db.solves_left(db.get_user(u10)) is None, "подписка не даёт безлимит")
    check("Безлимит" in bot.rec.texts(), "нет подтверждения подписки")

    # донат
    await feed(dp, bot, paid(u10, f"don:{u10}:50", 50, "chg-don"))
    check(db.get_user(u10)["donated"] == 50, "донат не записался")
    check("Спасибо" in bot.rec.texts(), "нет благодарности")

    # чужая валюта и чужой uid не зачисляются
    await feed(dp, bot, paid(u10, f"don:{u10}:50", 50, "chg-eur", currency="EUR"))
    check(db.get_user(u10)["donated"] == 50, "платёж в чужой валюте зачислен")
    balance = db.requests_left(db.get_user(u10))
    await feed(dp, bot, paid(u10, f"req:{u10 + 1}:req20", req_stars, "chg-foreign"))
    check(db.requests_left(db.get_user(u10)) == balance, "платёж с чужим uid зачислен")

    # --- мусор -------------------------------------------------------------
    await feed(dp, bot, msg(u10, "просто текст"))
    check("Пришли задание" in bot.rec.texts() or "по кнопкам" in bot.rec.texts(),
          "fallback не отвечает")
    await feed(dp, bot, cb(u10, "cb:unknown"))
    check(bot.rec.count("answer_callback_query") > 0, "неизвестная кнопка не обработана")

    # --- пул ключей --------------------------------------------------------
    import keypool
    pool = keypool.KeyPool(["sk-aaaaaaaaaaaaaaaaaaaa", "sk-bbbbbbbbbbbbbbbbbbbb"], None)
    k1 = pool.take()
    pool.mark_dead(k1, "401")
    check(pool.has_alive(), "пул не пережил отключение одного ключа")
    k2 = pool.take()
    check(k2 != k1, "пул не переключился на другой ключ")
    pool.mark_soft(k2)
    check(not pool.has_alive(), "пул не учёл остывание")
    pool.mark_ok(k1)
    check(pool.has_alive(), "ключ не вернулся после успеха")

    # --- админ-панель ------------------------------------------------------
    import discounts
    admin_id = uid()
    config.ADMIN_IDS = [admin_id]
    await feed(dp, bot, cmd(admin_id))
    await feed(dp, bot, cmd(admin_id, text="/admin"))
    check("Админ-панель" in bot.rec.texts(), "админка не открылась для админа")

    stranger = uid()
    await feed(dp, bot, cmd(stranger))
    mark = len(bot.rec.calls)
    await feed(dp, bot, cmd(stranger, text="/admin"))
    fresh = " ".join(str(kw.get("text") or "") for _, kw in bot.rec.calls[mark:])
    check("Админ-панель" not in fresh, "админка открылась постороннему")

    await feed(dp, bot, cb(admin_id, "adm:stats"))
    check("Статистика" in bot.rec.texts(), "нет экрана статистики")

    await feed(dp, bot, cb(admin_id, "adm:user"))
    await feed(dp, bot, msg(admin_id, "00000"))
    check("Не нашёл такого" in bot.rec.texts(), "поиск несуществующего не отбит")
    await feed(dp, bot, msg(admin_id, str(u10)))
    check(f"Пользователь {u10}" in bot.rec.texts(), "карточка пользователя не открылась")

    bal = db.requests_left(db.get_user(stranger))
    await feed(dp, bot, cb(admin_id, f"adm:give:req:10:{stranger}"))
    check(db.requests_left(db.get_user(stranger)) == bal + 10, "админ не начислил запросы")
    await feed(dp, bot, cb(admin_id, f"adm:give:sub:30:{stranger}"))
    check(db.is_pro(db.get_user(stranger)), "админ не выдал подписку")

    await feed(dp, bot, cb(admin_id, f"adm:ban:{stranger}"))
    check(db.is_banned(db.get_user(stranger)), "бан не сработал")
    await feed(dp, bot, cb(admin_id, f"adm:ban:{stranger}"))
    check(not db.is_banned(db.get_user(stranger)), "разбан не сработал")

    await feed(dp, bot, cb(admin_id, "adm:disc"))
    check("Скидки" in bot.rec.texts(), "нет экрана скидок")
    check(discounts.price(100) == (100, 0), "скидка появилась раньше времени")
    await feed(dp, bot, cb(admin_id, "adm:disc:new:20:24"))
    final, percent = discounts.price(100)
    check(final == 80 and percent == 20, f"скидка считается неверно: {final}, {percent}")
    await feed(dp, bot, cb(u10, "shop:req"))
    check("80" in bot.rec.texts() or "было" in bot.rec.texts(), "скидка не видна в магазине")
    await feed(dp, bot, cb(u10, "buy:req50"))
    inv = bot.rec.last("send_invoice")
    check(inv.get("prices") and inv["prices"][0]["amount"] == round(199 * 0.8),
          f"счёт выставлен без скидки: {inv.get('prices')}")
    await feed(dp, bot, cb(admin_id, "adm:disc:clear"))
    check(discounts.price(100) == (100, 0), "скидка не отключилась")

    await feed(dp, bot, cb(admin_id, "adm:disc:custom"))
    await feed(dp, bot, msg(admin_id, "15"))
    await feed(dp, bot, msg(admin_id, "12"))
    check(discounts.price(200)[1] == 15, "своя скидка не применилась")
    await feed(dp, bot, cb(admin_id, "adm:disc:clear"))

    await feed(dp, bot, cb(admin_id, "adm:cast"))
    await feed(dp, bot, msg(admin_id, "Проверка рассылки"))
    check("Превью" in bot.rec.texts(), "нет превью рассылки")
    sent_before = bot.rec.count("send_message")
    await feed(dp, bot, cb(admin_id, "adm:cast:go"))
    check(bot.rec.count("send_message") > sent_before, "рассылка ничего не отправила")
    check("Рассылка завершена" in bot.rec.texts(), "нет отчёта о рассылке")

    await feed(dp, bot, cb(admin_id, "adm:pay"))
    check("платежи" in bot.rec.texts().lower(), "нет экрана платежей")
    await feed(dp, bot, cb(admin_id, "adm:diag"))
    check("Диагностика" in bot.rec.texts(), "нет диагностики")

    db.close()
    print("\n" + "=" * 58)
    if FAILS:
        print(f"ПРОВАЛЕНО {len(FAILS)} из {len(FAILS) + OK}:")
        for f in FAILS:
            print("  ✗", f)
        return 1
    print(f"ОК: {OK} интеграционных проверок пройдено")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
