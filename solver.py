"""Офлайн-ядро: решает школьную математику с пошаговым разбором, без интернета.

Поддерживает:
* примеры на арифметику: `(1/2 + 3/4) * 8`, `12,5 * 4`, `2^10`
* линейные уравнения: `2x + 3 = 7`, `5(x - 2) = 3x + 1`
* квадратные уравнения: `x^2 - 5x + 6 = 0`
* проценты: `20% от 150`, `сколько процентов 30 от 150`, `число 120 уменьшили на 25%`
* дроби: точный ответ и приведение

Никакого eval: свой токенизатор и разбор в многочлен степени ≤ 2.
"""
from __future__ import annotations

import re
from fractions import Fraction

MAX_DEGREE = 2


class MathError(Exception):
    pass


# --- вывод чисел -----------------------------------------------------------
def fmt(value: Fraction | float | int) -> str:
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    # красиво, если знаменатель даёт конечную десятичную дробь
    den = value.denominator
    for p in (2, 5):
        while den % p == 0:
            den //= p
    if den == 1:
        digits = 0
        d = value.denominator
        while d % 10 != 1 and digits < 6:
            d //= 2 if d % 2 == 0 else 5
            digits += 1
        num, rest = divmod(abs(value.numerator) * 10 ** digits, value.denominator)
        sign = "-" if value < 0 else ""
        text = str(num).rjust(digits + 1, "0")
        out = f"{text[:-digits]},{text[-digits:]}" if digits else text
        return (sign + out).rstrip("0").rstrip(",")
    return f"{value.numerator}/{value.denominator}"


def _num(text: str) -> Fraction:
    return Fraction(text.replace(",", "."))


# --- токенизация -----------------------------------------------------------
_TOKEN = re.compile(r"\s*(\d+[.,]?\d*|[a-zA-Zа-яА-Я]+|[-+*/^()=])")


def tokenize(expr: str) -> list[str]:
    text = expr.replace(" ", "").replace("·", "*").replace("×", "*").replace("÷", "/")
    text = text.replace("**", "^").replace("−", "-").replace("–", "-")
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise MathError(f"непонятный символ в «{text[pos:pos + 8]}»")
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


class Poly:
    """Многочлен 0..2 степени по x: c[0] + c[1]x + c[2]x²."""

    __slots__ = ("c",)

    def __init__(self, c0=0, c1=0, c2=0):
        self.c = [Fraction(c0), Fraction(c1), Fraction(c2)]

    def degree(self) -> int:
        if self.c[2] != 0:
            return 2
        if self.c[1] != 0:
            return 1
        return 0

    @staticmethod
    def const(v) -> "Poly":
        return Poly(v, 0, 0)

    @staticmethod
    def var() -> "Poly":
        return Poly(0, 1, 0)

    def __add__(self, o: "Poly") -> "Poly":
        return Poly(*(a + b for a, b in zip(self.c, o.c)))

    def __neg__(self) -> "Poly":
        return Poly(*(-a for a in self.c))

    def __sub__(self, o: "Poly") -> "Poly":
        return self + (-o)

    def __mul__(self, o: "Poly") -> "Poly":
        if self.degree() + o.degree() > MAX_DEGREE:
            raise MathError("слишком высокая степень — такое решаю через AI-режим")
        out = [Fraction(0)] * 3
        for i, a in enumerate(self.c):
            if not a:
                continue
            for j, b in enumerate(o.c):
                if not b:
                    continue
                out[i + j] += a * b
        return Poly(*out)

    def __truediv__(self, o: "Poly") -> "Poly":
        if o.degree() != 0:
            raise MathError("деление на выражение с x — упрощу в AI-режиме")
        if o.c[0] == 0:
            raise MathError("деление на ноль")
        return Poly(*(a / o.c[0] for a in self.c))

    def __pow__(self, power: int) -> "Poly":
        if power < 0:
            raise MathError("степень должна быть неотрицательной")
        if self.is_const():
            return Poly.const(self.c[0] ** power)
        if power > MAX_DEGREE:
            raise MathError("степень выше второй — такое решаю через AI-режим")
        result, base = Poly.const(1), self
        for _ in range(power):
            result = result * base
        return result

    def is_const(self) -> bool:
        return self.degree() == 0

    def value(self) -> Fraction:
        if not self.is_const():
            raise MathError("выражение содержит x")
        return self.c[0]


class Parser:
    def __init__(self, tokens: list[str]):
        self.t = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise MathError("выражение обрывается")
        self.i += 1
        return tok

    def parse(self) -> Poly:
        if not self.t:
            raise MathError("пустое выражение")
        result = self.expr()
        if self.peek() is not None:
            raise MathError(f"лишнее «{self.peek()}»")
        return result

    def expr(self) -> Poly:
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            rhs = self.term()
            node = node + rhs if op == "+" else node - rhs
        return node

    def term(self) -> Poly:
        node = self.factor()
        while True:
            tok = self.peek()
            if tok in ("*", "/"):
                op = self.take()
                rhs = self.factor()
                node = node * rhs if op == "*" else node / rhs
            elif tok is not None and (tok.isdigit() or tok == "(" or tok.lower() == "x"
                                      or re.fullmatch(r"[a-zA-Zа-яА-Я]+", tok or "")):
                node = node * self.factor()  # неявное умножение: 2x, 3(x+1)
            else:
                return node

    def factor(self) -> Poly:
        tok = self.peek()
        if tok == "-":
            self.take()
            return -self.factor()
        if tok == "+":
            self.take()
            return self.factor()
        node = self.atom()
        if self.peek() == "^":
            self.take()
            power_tok = self.take()
            if not power_tok.isdigit():
                raise MathError("степень должна быть целым числом")
            node = node ** int(power_tok)
        return node

    def atom(self) -> Poly:
        tok = self.take()
        if tok == "(":
            node = self.expr()
            if self.peek() != ")":
                raise MathError("не закрыта скобка")
            self.take()
            return node
        if re.fullmatch(r"\d+[.,]?\d*", tok):
            return Poly.const(_num(tok))
        if tok.lower() == "x":
            return Poly.var()
        raise MathError(f"не понимаю «{tok}»")


# --- решение ---------------------------------------------------------------
def _steps_quadratic(a: Fraction, b: Fraction, c: Fraction) -> tuple[list[str], str]:
    steps = [f"Уравнение вида ax² + bx + c = 0, где a = {fmt(a)}, b = {fmt(b)}, c = {fmt(c)}."]
    d = b * b - 4 * a * c
    steps.append(f"Дискриминант: D = b² − 4ac = {fmt(b)}² − 4·{fmt(a)}·{fmt(c)} = {fmt(d)}.")
    if d < 0:
        steps.append("D < 0 — действительных корней нет.")
        return steps, "корней нет"
    root = d ** 0.5 if d >= 0 else None
    exact = None
    for k in range(0, 200):
        if Fraction(k * k) == d:
            exact = Fraction(k)
            break
    if d == 0:
        x0 = -b / (2 * a)
        steps.append("D = 0 — один корень: x = −b / (2a).")
        steps.append(f"x = −({fmt(b)}) / (2·{fmt(a)}) = {fmt(x0)}.")
        return steps, f"x = {fmt(x0)}"
    if exact is not None:
        x1 = (-b - exact) / (2 * a)
        x2 = (-b + exact) / (2 * a)
        steps.append(f"√D = {fmt(exact)}.")
        steps.append("x₁ = (−b − √D) / 2a, x₂ = (−b + √D) / 2a.")
        steps.append(f"x₁ = ({fmt(-b)} − {fmt(exact)}) / {fmt(2 * a)} = {fmt(x1)}.")
        steps.append(f"x₂ = ({fmt(-b)} + {fmt(exact)}) / {fmt(2 * a)} = {fmt(x2)}.")
        return steps, f"x₁ = {fmt(x1)}, x₂ = {fmt(x2)}"
    x1 = (-float(b) - float(root)) / (2 * float(a))
    x2 = (-float(b) + float(root)) / (2 * float(a))
    steps.append(f"√D ≈ {fmt(round(root, 4))} — точного корня нет, считаем приближённо.")
    steps.append(f"x₁ ≈ {fmt(round(x1, 4))}, x₂ ≈ {fmt(round(x2, 4))}.")
    return steps, f"x₁ ≈ {fmt(round(x1, 4))}, x₂ ≈ {fmt(round(x2, 4))}"


def _clean_math(text: str) -> str:
    text = text.lower()
    text = re.sub(r"(реши|решить|решите|уравнение|пример|вычисли|вычислить|найдите|найти|"
                  r"значение выражения|ответ|пожалуйста|плиз|помогите|помоги|мне|"
                  r"это|задание|номер|класс|математика|алгебра)\b", " ", text)
    text = text.replace("х", "x").replace("икс", "x")
    return text.strip(" .,:;!?—")


PERCENT_OF = re.compile(
    r"(\d+[.,]?\d*)\s*%\s*(?:от|от числа|от суммы)?\s*(?:числа\s*)?(\d+[.,]?\d*)")
PERCENT_WHAT = re.compile(
    r"(?:сколько|какой|какую)\s+%?\s*процент\w*\s*(?:составляет|это)?\s*"
    r"(\d+[.,]?\d*)\s*(?:от|из)\s*(\d+[.,]?\d*)")
PERCENT_INCREASE = re.compile(
    r"(?:число|цена|зарплата|товар)?\s*(\d+[.,]?\d*)\s*(увеличил\w*|уменьшил\w*|повысил\w*|"
    r"понизил\w*|подорожал\w*|подешевел\w*)\s*на\s*(\d+[.,]?\d*)\s*%")


def _percent(text: str) -> dict | None:
    low = text.lower()
    m = PERCENT_WHAT.search(low)
    if m:
        part, whole = _num(m.group(1)), _num(m.group(2))
        if whole == 0:
            raise MathError("деление на ноль")
        value = part / whole * 100
        steps = [
            "Часть делим на целое и умножаем на 100%:",
            f"{fmt(part)} ÷ {fmt(whole)} × 100% = {fmt(value)}%.",
        ]
        if value.denominator != 1:
            steps.append(f"Точное значение: {fmt(value)}% (≈ {float(value):.2f}%).".replace(".", ","))
        return {"kind": "percent", "given": f"{fmt(part)} от {fmt(whole)}",
                "steps": steps, "answer": f"{fmt(round(float(value), 2))}%"}

    m = PERCENT_OF.search(low)
    if m and "%" in low:
        pct, base = _num(m.group(1)), _num(m.group(2))
        value = base * pct / 100
        steps = [
            "Процент — это сотая часть числа. Переводим: "
            f"{fmt(pct)}% = {fmt(pct)}/100 = {fmt(pct / 100)}.",
            f"Умножаем число на эту долю: {fmt(base)} × {fmt(pct / 100)} = {fmt(value)}.",
            f"Проверка: 1% от {fmt(base)} — это {fmt(base / 100)}, а нам нужно {fmt(pct)}%.",
        ]
        return {"kind": "percent", "given": f"{fmt(pct)}% от {fmt(base)}",
                "steps": steps, "answer": fmt(value)}

    m = PERCENT_INCREASE.search(low)
    if m:
        base, word, pct = _num(m.group(1)), m.group(2), _num(m.group(3))
        up = word.startswith(("увел", "повыс", "подорож"))
        delta = base * pct / 100
        value = base + delta if up else base - delta
        steps = [
            f"Сначала находим, сколько составляет {fmt(pct)}%: "
            f"{fmt(base)} × {fmt(pct / 100)} = {fmt(delta)}.",
            ("Прибавляем к исходному числу: " if up else "Вычитаем из исходного числа: ")
            + f"{fmt(base)} {'+' if up else '−'} {fmt(delta)} = {fmt(value)}.",
        ]
        return {"kind": "percent", "given": f"{fmt(base)} {'+' if up else '−'} {fmt(pct)}%",
                "steps": steps, "answer": fmt(value)}
    return None


def solve_equation(left: str, right: str) -> dict:
    lp = Parser(tokenize(left)).parse()
    rp = Parser(tokenize(right)).parse()
    diff = lp - rp
    a, b, c = diff.c
    steps: list[str] = []
    given = f"{left.strip()} = {right.strip()}"
    if c != 0:
        steps, answer = _steps_quadratic(c, b, a)
        return {"kind": "quadratic", "given": given, "steps": steps, "answer": answer}
    if b == 0:
        if a == 0:
            return {"kind": "identity", "given": given,
                    "steps": ["Слева и справа одно и то же выражение — x сокращается."],
                    "answer": "x — любое число"}
        return {"kind": "contradiction", "given": given,
                "steps": [f"Получаем {fmt(a)} = 0, что неверно."], "answer": "корней нет"}
    steps = [
        "Переносим всё с x в одну сторону, числа — в другую (знак меняется на противоположный).",
        f"Получаем: {fmt(b)}·x = {fmt(-a)}.",
        f"Делим обе части на {fmt(b)}: x = {fmt(-a)} ÷ {fmt(b)} = {fmt(-a / b)}.",
        "Проверка: подставляем найденный x в исходное уравнение — обе части должны совпасть.",
    ]
    return {"kind": "linear", "given": given, "steps": steps, "answer": f"x = {fmt(-a / b)}"}


def solve_text(text: str) -> dict:
    """Пытается решить задачу из текста. Бросает MathError, если не по зубам."""
    raw = text.strip()
    if not raw:
        raise MathError("пустая задача")

    percent = _percent(raw)
    if percent:
        return percent

    cleaned = _clean_math(raw)
    stray = set(re.findall(r"[a-z]", cleaned)) - {"x"}
    if stray:
        raise MathError(f"в выражении есть другие буквы: {''.join(sorted(stray))} — это AI-режим")
    cleaned = re.sub(r"[^0-9x+\-*/^()=,. ]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" =.,")
    if not cleaned or not re.search(r"\d", cleaned):
        raise MathError("в тексте нет чисел — это задача на смысл, её разберёт AI-режим")

    if "=" in cleaned:
        if cleaned.count("=") > 1:
            raise MathError("системы уравнений пока не решаю офлайн")
        left, right = cleaned.split("=", 1)
        return solve_equation(left, right)

    poly = Parser(tokenize(cleaned)).parse()
    if not poly.is_const():
        raise MathError("выражение с x без знака равенства — нечего решать")
    value = poly.value()
    steps = [
        f"Считаем по действиям, соблюдая порядок: скобки → степени → умножение и деление → сложение и вычитание.",
        f"Значение выражения: {fmt(value)}.",
    ]
    if value.denominator != 1:
        steps.append(f"Это {float(value):.4f} в десятичной записи.".replace(".", ","))
    return {"kind": "arithmetic", "given": cleaned, "steps": steps, "answer": fmt(value)}


# --- проверка чужого решения ----------------------------------------------
def extract_numbers(text: str) -> list[Fraction]:
    out = []
    for m in re.finditer(r"-?\d+[.,]?\d*", text):
        try:
            out.append(_num(m.group(0)))
        except (ValueError, ZeroDivisionError):
            continue
    return out


def check_student_answer(task: str, student: str) -> dict:
    """Сравнивает ответ ученика с офлайн-решением. ok=None — сравнить не смогли."""
    try:
        truth = solve_text(task)
    except MathError:
        return {"ok": None, "reason": "не смог решить сам — проверю через AI-режим"}

    target_numbers = [n for n in extract_numbers(truth["answer"])]
    student_numbers = extract_numbers(student)
    if not target_numbers or not student_numbers:
        return {"ok": None, "reason": "в ответе нет чисел для сравнения"}
    hit = any(abs(s - t) <= Fraction(1, 1000) for s in student_numbers for t in target_numbers)
    return {"ok": hit, "truth": truth["answer"], "steps": truth["steps"],
            "reason": "совпало с решением" if hit else "не совпало с правильным ответом"}
