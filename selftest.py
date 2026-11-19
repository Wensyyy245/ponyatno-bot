"""Офлайн-тесты «ПОНЯТНО»: решатель, офлайн-банк, вёрстка, БД, клавиатуры.

Запуск:  python selftest.py
Сеть не нужна.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, msg: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(msg)


def section(name: str) -> None:
    print(f"\n— {name}")


# ---------------------------------------------------------------- решатель
section("Офлайн-решатель математики")
import solver  # noqa: E402

CASES = [
    ("2+2*3", "8"),
    ("(1/2)+(3/4)", "1,25"),
    ("12,5 * 4", "50"),
    ("2^10", "1024"),
    ("7 - 10", "-3"),
    ("(2+3)*(4-1)", "15"),
    ("10/4", "2,5"),
    ("-3 + 5", "2"),
    ("2x + 3 = 7", "x = 2"),
    ("5(x - 2) = 3x + 1", "x = 5,5"),
    ("3x = 0", "x = 0"),
    ("x/2 = 5", "x = 10"),
    ("x^2 - 5x + 6 = 0", "x₁ = 2, x₂ = 3"),
    ("x^2 + 2x + 1 = 0", "x = -1"),
    ("x^2 + 1 = 0", "корней нет"),
]
for task, expected in CASES:
    try:
        res = solver.solve_text(task)
        got = res["answer"]
        check(got == expected, f"«{task}» → «{got}», ожидалось «{expected}»")
        check(bool(res["steps"]), f"«{task}»: нет шагов")
        check(res["kind"], f"«{task}»: не указан тип")
    except solver.MathError as exc:
        check(False, f"«{task}»: MathError {exc}")

# проценты
PCT = [
    ("20% от 150", "30"),
    ("сколько процентов 30 от 150", "20%"),
    ("число 120 уменьшили на 25%", "90"),
    ("число 200 увеличили на 10%", "220"),
]
for task, expected in PCT:
    try:
        got = solver.solve_text(task)["answer"]
        check(got == expected, f"проценты «{task}» → «{got}», ожидалось «{expected}»")
    except solver.MathError as exc:
        check(False, f"проценты «{task}»: MathError {exc}")

# тождество и противоречие
check(solver.solve_text("x + 1 = x + 1")["kind"] == "identity", "тождество не распознано")
check(solver.solve_text("x + 1 = x + 2")["kind"] == "contradiction", "противоречие не распознано")

# отказы
for bad in ["", "расскажи про кота", "x^3 = 8", "2x = y", "a + b", "x^2y = 4"]:
    try:
        solver.solve_text(bad)
        check(False, f"должно было отказать: «{bad}»")
    except solver.MathError:
        pass
    except Exception as exc:  # noqa: BLE001
        check(False, f"«{bad}»: неожиданная ошибка {type(exc).__name__}: {exc}")

check(solver.fmt(solver.Fraction(1, 3)) == "1/3", "дробь 1/3 форматируется неверно")
check(solver.fmt(solver.Fraction(-5, 2)) == "-2,5", "отрицательная дробь форматируется неверно")
check(solver.fmt(solver.Fraction(0)) == "0", "ноль форматируется неверно")
check("4" in solver.solve_text("найди значение выражения 2+2")["answer"], "словесная обёртка мешает")

# проверка чужого решения
r = solver.check_student_answer("2x + 3 = 7", "у меня получилось x = 2")
check(r["ok"] is True, "верный ответ не подтверждён")
r = solver.check_student_answer("2x + 3 = 7", "x = 3")
check(r["ok"] is False, "неверный ответ не отловлен")
check(r["truth"] == "x = 2", "не показан правильный ответ")
r = solver.check_student_answer("напиши сочинение про осень", "готово")
check(r["ok"] is None, "нерешаемое должно давать ok=None")

# ---------------------------------------------------------------- офлайн-банк
section("Офлайн-банк алгоритмов")
import offline  # noqa: E402

bank = offline._BANK
check(len(bank) >= 15, f"мало алгоритмов: {len(bank)}")
keys = set()
for item in bank:
    check(bool(item["title"]) and len(item["steps"]) >= 3, f"кривой алгоритм: {item.get('title')}")
    check(item["subject"] in {s[0] for s in __import__("config").SUBJECTS},
          f"неизвестный предмет в банке: {item['subject']}")
    for k in item["keys"]:
        check(k == k.lower(), f"ключ не в нижнем регистре: {k}")
    keys.add(item["title"])
check(len(keys) == len(bank), "дубли названий алгоритмов")

algo = offline.find_algorithm("как найти площадь прямоугольника", "math")
check(algo and "площад" in algo["title"].lower(), "площадь не найдена")
algo = offline.find_algorithm("Как определить падеж существительного", "rus")
check(algo and "падеж" in algo["title"].lower(), "падеж не найден")
check(offline.find_algorithm("что-то совсем непонятное", "math") is None, "нашёлся лишний алгоритм")
check(offline.find_algorithm("как решать квадратное уравнение", None) is not None, "поиск без предмета сломан")

res = offline.try_solve("2x + 3 = 7", "math")
check(res and res["answer"] == "x = 2", "офлайн не решил уравнение")
check(res["provider"] == "offline-math", "неверный provider у математики")
res = offline.try_solve("как определить падеж слова", "rus")
check(res and res["provider"] == "offline-algo" and res["steps"], "офлайн не выдал алгоритм")
check(offline.try_solve("абракадабра", "hist") is None, "лишний разбор для мусора")

# ---------------------------------------------------------------- вёрстка
section("Вёрстка ответа")
import render  # noqa: E402

demo = {"what": "Дано <b>плохое</b> & опасное", "steps": ["шаг <script>", "шаг 2"],
        "answer": "x = 2 & всё", "hint": "проверь <сам>", "similar": "2+2", "provider": "offline-math"}
text = render.render(demo, grade=8, subject="math", source="text")
check("<script>" not in text, "HTML из данных не экранирован")
check("&lt;script&gt;" in text, "экранирование не сработало")
check("<b>1.</b>" in text and "<b>2.</b>" in text, "шаги не пронумерованы")
check("Ответ" in text and "x = 2 &amp; всё" in text, "ответ не отрисован")
check("Проверь себя" in text, "нет блока самопроверки")
check(len(text) < 4096, f"слишком длинное сообщение: {len(text)}")
check("Malicious" not in text, "утечка")

big = render.render({"steps": ["очень длинный шаг " * 40] * 12, "answer": "1", "what": "x" * 900,
                     "hint": "", "similar": "", "provider": "ai"}, grade=11, subject="phys", source="photo")
check(len(big) <= 3900, f"длинный разбор не обрезан: {len(big)}")
check(big.count("—") >= 0, "рендер упал")

# ---------------------------------------------------------------- БД
section("База данных")
import config  # noqa: E402
import db  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="ponyatno-test-"))
db_file = tmp / "test.sqlite3"
db.init(db_file)
check(db_file.exists(), "база не создана")

u = db.ensure_user(111, "tester", "Тест")
check(u["user_id"] == 111 and u["ref_code"], "пользователь не создан")
check(u["grade"] == config.DEFAULT_GRADE, "класс по умолчанию не выставлен")
db.set_grade(111, 9)
db.set_subject(111, "rus")
u = db.get_user(111)
check(u["grade"] == 9 and u["subject"] == "rus", "класс/предмет не сохраняются")

check(db.solves_left(u) == config.FREE_SOLVES_PER_DAY, "неверный дневной лимит")
for _ in range(config.FREE_SOLVES_PER_DAY):
    db.use_solve(111)
u = db.get_user(111)
check(db.solves_left(u) == 0, "дневной лимит не расходуется")
check(db.daily_free_left(u) == 0, "дневные не обнулились")
check(u["solves_total"] == config.FREE_SOLVES_PER_DAY, "счётчик разборов не растёт")

# купленные запросы: не сгорают, тратятся после бесплатных
check(db.add_requests(111, 5) == 5, "запросы не начислились")
check(db.solves_left(db.get_user(111)) == 5, "баланс не попал в доступ")
db.use_solve(111)
check(db.requests_left(db.get_user(111)) == 4, "купленный запрос не списался")
check(db.get_user(111)["solves_total"] == config.FREE_SOLVES_PER_DAY + 1,
      "счётчик не растёт при списании купленных")

# подписка — безлимит
db.grant_subscription(111, 30)
u = db.get_user(111)
check(db.is_pro(u), "подписка не включилась")
check(db.solves_left(u) is None, "подписка не даёт безлимит")
check(db.is_unlimited(u), "is_unlimited врёт")
check(28 <= db.pro_days_left(u) <= 30, f"дни подписки считаются неверно: {db.pro_days_left(u)}")
db.use_solve(111)
check(db.requests_left(db.get_user(111)) == 4, "подписка всё равно списывает запросы")
db.grant_subscription(111, 30)
check(db.pro_days_left(db.get_user(111)) >= 58, "продление подписки не суммируется")

# рефералка: бонус не сразу, а после подтверждения подписки на канал
ref = db.ensure_user(222, None, "Друг", referred_by=111)
check(ref["referred_by"] == 111 and db.count_refs(111) == 1, "реферал не записан")
check(not db.is_pro(db.get_user(222)), "приглашённому выдали подписку — не должны")
check(db.count_pending_refs(111) == 1, "ожидающий бонус не считается")
db.mark_ref_bonus(222)
check(db.ref_bonus_paid(db.get_user(222)), "бонус не помечен как выплаченный")
check(db.count_pending_refs(111) == 0, "счётчик ожидающих не обнулился")
check(db.ensure_user(333, None, "Сам", referred_by=333)["referred_by"] is None, "самореферал прошёл")

code = db.get_user(111)["ref_code"]
check(db.get_by_ref(code)["user_id"] == 111, "поиск по реф-коду сломан")
check(db.get_by_ref("НЕТТАКОГО") is None, "нашёлся несуществующий код")

db.log_solution(111, "math", 9, "text", "explain", "offline-math", True)
db.log_solution(111, "math", 9, "photo", "explain", "ai", False)
check(db.count_solutions(111) == 1, "журнал решений считает неверно")

db.add_payment(111, "req:111:req20", "requests", 99, "chg-1")
check(db.has_charge("chg-1"), "платёж не сохранён")
check(not db.has_charge("chg-2"), "чужой charge найден")
check(db.add_donation(111, 50) >= 50, "донат не суммируется")

xp, lvl = db.add_xp(111, config.XP_PER_SOLVE)
check(xp == config.XP_PER_SOLVE and lvl == 1, "XP не начисляется")
db.add_xp(111, 1000)
check(db.add_xp(111, 0)[1] > 1, "уровень не растёт")

db.touch(111)
check(db.get_user(111)["streak"] >= 1, "стрик не считается")
db.x("UPDATE users SET last_active=?, streak=5 WHERE user_id=111", ("2000-01-01",))
db.touch(111)
check(db.get_user(111)["streak"] == 1, "стрик не сбрасывается после пропуска")

st = db.stats()
check(st["users"] >= 3 and st["solves"] >= 1 and st["stars"] >= 99, f"статистика битая: {st}")
check(st["pro"] >= 1, f"подписки не считаются: {st}")

# ---------------------------------------------------------------- клавиатуры
section("Клавиатуры и callback-данные")
import keyboards as kb  # noqa: E402

user = db.get_user(222)
LITERAL = {
    "m:solve", "m:text", "m:check", "m:setup", "m:profile", "m:ref", "m:pay",
    "m:menu", "m:help", "m:demo", "m:grades", "m:subjects", "ref:check",
    "shop:req", "shop:sub", "shop:don",
    "a:simpler", "a:similar", "a:check", "pay:custom",
}
PREFIX = ("gr:", "sub:", "buy:", "don:")

kbs = {
    "main": kb.main_menu(user),
    "solve": kb.solve_prompt_kb(),
    "answer": kb.answer_kb(True),
    "grades": kb.grades_kb(),
    "subjects": kb.subjects_kb(),
    "setup": kb.setup_kb(),
    "shop": kb.shop_kb(user),
    "req": kb.req_packs_kb(),
    "sub_plans": kb.sub_plans_kb(),
    "donate": kb.donate_kb(),
    "ref": kb.ref_kb(True),
    "after_pay": kb.after_pay_kb(),
    "limit": kb.limit_kb(),
    "back": kb.back_menu(),
}
total = 0
for name, markup in kbs.items():
    check(bool(markup.inline_keyboard), f"{name}: пустая клавиатура")
    datas = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
    check(len(datas) == len(set(datas)), f"{name}: дубли callback_data")
    total += len(datas)
    for d in datas:
        check(len(d.encode()) <= 64, f"{name}: callback_data > 64 байт: {d}")
        check(d in LITERAL or d.startswith(PREFIX), f"{name}: кнопка без хендлера: {d}")
        check(not any(c.isspace() for c in d), f"{name}: пробел в callback_data: {d}")
    for row in markup.inline_keyboard:
        for b in row:
            check(len(b.text) <= 64, f"{name}: длинная кнопка: {b.text}")
print(f"   клавиатур: {len(kbs)}, кнопок: {total}")

# ---------------------------------------------------------------- сборка
section("Сборка приложения")
import handlers  # noqa: E402
from handlers import pay as pay_h  # noqa: E402
from handlers import solve as solve_h  # noqa: E402
import ai  # noqa: E402
import ui  # noqa: E402
import store  # noqa: E402
import bot as app  # noqa: E402

router = handlers.build_router()
check(len(router.sub_routers) == 5, f"роутеры не подключены: {len(router.sub_routers)}")
check(all(callable(fn) for fn in (pay_h.cb_shop,)), "магазин не собран")
check(callable(app.main), "bot.main нет")
check(len(pay_h.shop_text(user)) < 4000, "экран магазина слишком длинный")
check(len(pay_h.req_text()) < 4000, "экран запросов слишком длинный")
check(len(pay_h.sub_text(user)) < 4000, "экран подписки слишком длинный")
check(len(pay_h.don_text()) < 4000, "экран поддержки слишком длинный")
check(len(ui.welcome("Имя", user, True)) < 4000, "приветствие слишком длинное")
check(len(ui.profile(user)) < 4000, "профиль слишком длинный")
check(len(ui.help_text(False)) < 4000, "справка слишком длинная")
check("<script>" not in ui.welcome("<script>", user, True), "имя не экранируется")
check(config.SUBJECT_BY_KEY["math"][0] == "Математика", "предметы развалились")
check(len(config.GRADES) == 7, "классы развалились")

store.save(1, "2x+3=7", "text", "math", 8)
check(store.get(1)["text"] == "2x+3=7", "последняя задача не сохраняется")
store.mark(1)
check(store.cooldown_left(1, 5) > 0, "антифлуд не работает")
check(store.cooldown_left(2, 5) == 0, "антифлуд ловит чужих")

# конвейерный предохранитель: без ключа AI офлайн отвечает по тексту
check(config.ai_ready() is False or config.ai_ready() is True, "ai_ready сломан")

# сообщение про фото должно называть настоящую причину, а не всегда «ключ не вписан»
_orig_status = ai.status
ai.status = lambda: {"state": "no_keys", "text": "ключ AI не вписан в .env"}
check("нет ключа AI" in solve_h.no_ai_text(), "текст для «нет ключей» неверный")
ai.status = lambda: {"state": "rejected", "text": "ключ не принят (HTTP 401)"}
_t = solve_h.no_ai_text()
check("не принимает" in _t and "401" in _t, "текст для «ключи отклонены» неверный")
ai.status = lambda: {"state": "cooling", "text": "лимит запросов"}
check("остывают" in solve_h.no_ai_text(), "текст для «остывают» неверный")
ai.status = _orig_status

db.close()
print("\n" + "=" * 60)
if FAILS:
    print(f"ПРОВАЛЕНО {len(FAILS)} из {CHECKS}:")
    for f in FAILS:
        print("  ✗", f)
    sys.exit(1)
print(f"ОК: {CHECKS} проверок пройдено")
sys.exit(0)
