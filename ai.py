"""AI-слой: фото или текст задачи → разбор по шагам.

Провайдер — любой OpenAI-совместимый (ProxyAPI, VseGPT, OpenRouter, локальный
gateway). Ключ и модель берутся из .env. Без ключа модуль честно падает
в AIUnavailable, и бот уходит в офлайн-режим.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re

import aiohttp

import config
import keypool

log = logging.getLogger("ai")

POOL = keypool.KeyPool(config.ai_keys(), config.AI_KEYS_STATE)
_QUOTA_NOTE = ""  # последняя причина «нет средств» от провайдера


TEACHER = (
    "Ты школьный учитель. Ученик в {grade} классе, присылает домашку фото или текстом. "
    "Объясняй коротко, по-русски, чтобы он понял и решил следующее сам.\n"
    "Шаги — отдельными пунктами, с пояснением почему. Не больше 5 шагов, до 220 символов. "
    "Если на фото несколько заданий — возьми первое. Если не задача — попроси переснять. "
    "Ответ строго JSON без markdown."
)

SCHEMA_HINT = """Верни JSON:
{{
  "what": "что дано, одной строкой",
  "steps": ["шаг 1 с объяснением", "шаг 2", "..."],
  "answer": "итоговый ответ",
  "hint": "один вопрос ученику на самопроверку",
  "similar": "одна похожая задача для тренировки, без решения"
}}

Требования к размеру: шагов не больше 5, каждый до 220 символов, без markdown и формул в LaTeX.
Пиши коротко: ответ должен целиком уложиться в один JSON."""

MODE_TASK = {
    "explain": "Разбери это задание по шагам. Предмет: {subject}.",
    "simpler": ("Ученик не понял прошлое объяснение. Объясни ТУ ЖЕ задачу заново, "
                "проще: короче шаги, бытовые примеры, без формул там, где можно. Предмет: {subject}."),
    "similar": ("Придумай ОДНУ похожую задачу того же типа и сложности и реши её по шагам. "
                "Предмет: {subject}."),
    "check": ("Ученик прислал своё решение. Найди ошибку, если она есть, и объясни, "
              "что именно не так. Если всё верно — подтверди и покажи более короткий путь. "
              "Предмет: {subject}."),
}


class AIUnavailable(Exception):
    """Ключ не настроен или провайдер отключён."""


class AIError(Exception):
    """Провайдер ответил ошибкой."""


class AuthError(AIError):
    """Ключ не принят (401/403) — его надо выключить."""


class RateLimitError(AIError):
    """Слишком много запросов (429) — ключ остывает."""


class QuotaError(AIError):
    """Ключ верный, но на счету провайдера нет денег (402)."""


def ready() -> bool:
    """Есть ли хоть один живой ключ прямо сейчас."""
    return POOL.has_alive()


def status() -> dict:
    """Состояние AI для честных сообщений пользователю.

    state: no_keys · rejected · cooling · ok · mock
    """
    if config.AI_FORCE_MOCK:
        return {"state": "mock", "text": "тестовый режим без сети"}
    keys = config.ai_keys()
    if not keys:
        return {"state": "no_keys", "text": "ключ AI не вписан в .env"}
    if POOL.has_alive():
        return {"state": "ok", "text": f"ключей в пуле: {len(keys)}"}
    stats = POOL.stats()
    if stats["cooling"] and not stats["dead"]:
        return {"state": "cooling", "text": "провайдер ограничил частоту запросов, ключи остывают"}
    if _QUOTA_NOTE:
        return {"state": "quota", "text": _QUOTA_NOTE}
    return {"state": "rejected", "text": POOL.last_reason()}


async def healthcheck() -> bool:
    """Один дешёвый запрос при старте: сразу выключает мёртвые ключи.

    Без этого бот обещает «фото включено», а потом падает на первом задании.
    """
    if config.AI_FORCE_MOCK or not POOL.size:
        return False
    tried: set[str] = set()
    while True:
        key = POOL.take(exclude=tried, include_dead=True)
        if key is None:
            return False
        tried.add(key)
        payload = {"model": config.AI_MODEL, "max_tokens": 1,
                   "messages": [{"role": "user", "content": "ок"}]}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            await _post(f"{config.AI_BASE_URL}/chat/completions", payload, headers)
        except QuotaError as exc:
            global _QUOTA_NOTE
            _QUOTA_NOTE = str(exc)
            log.warning("healthcheck: нет средств у провайдера — %s", exc)
            return False
        except AuthError as exc:
            POOL.mark_dead(key, f"проверка при старте: {exc}")
            continue
        except RateLimitError:
            POOL.mark_soft(key)
            continue
        except AIError as exc:
            log.warning("healthcheck: %s", exc)
            POOL.mark_fail(key)
            continue
        POOL.mark_ok(key)
        log.info("AI-режим подтверждён ключом %s", keypool.mask(key))
        return True


class AIAnswer(dict):
    """Результат: what, steps, answer, hint, similar, provider."""


def _user_text(task: str | None, mode: str, subject: str, grade: int,
               student: str | None, extra: str = "") -> str:
    parts = [TEACHER.format(grade=grade),
             MODE_TASK.get(mode, MODE_TASK["explain"]).format(subject=subject),
             SCHEMA_HINT]
    if extra:
        parts.append(extra)
    if task:
        parts.append(f"Задание:\n{task.strip()[:config.MAX_TEXT_LEN]}")
    if student:
        parts.append(f"Решение ученика:\n{student.strip()[:800]}")
    if not task:
        parts.append("Задание на фотографии выше.")
    return "\n\n".join(parts)


def _salvage(text: str) -> dict | None:
    """Достаёт поля из обрезанного JSON: ученик должен увидеть разбор, а не сырой текст."""
    def field(name: str) -> str:
        match = re.search(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
        return match.group(1) if match else ""

    def clean(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", " ").strip()

    block = re.search(r'"steps"\s*:\s*\[(.*)', text, re.S)
    raw_steps = re.findall(r'"((?:[^"\\]|\\.)*)"', block.group(1)) if block else []
    steps = [clean(s) for s in raw_steps if s.strip()]
    data = {"what": clean(field("what")), "steps": steps,
            "answer": clean(field("answer")), "hint": clean(field("hint")),
            "similar": clean(field("similar"))}
    if not any(data.values()):
        return None
    return data


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    if start < 0:
        return _salvage(text)
    chunk = text[start:]

    candidates = [chunk]
    end = chunk.rfind("}")
    if end > 0:
        candidates.append(chunk[: end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    # ответ обрезался по лимиту токенов — достраиваем закрывающие скобки
    for suffix in ('"}', '"]}', '}]}', '"]}}', ']}', '"}]\n}'):
        try:
            data = json.loads(chunk + suffix)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return _salvage(chunk)


def _normalize(data: dict, provider: str) -> AIAnswer:
    def s(key: str) -> str:
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            return "\n".join(str(v).strip() for v in value if str(v).strip())
        return str(value).strip() if value is not None else ""

    steps = data.get("steps") or []
    if isinstance(steps, str):
        steps = [line.strip(" -•\t") for line in steps.splitlines() if line.strip()]
    if not isinstance(steps, list):
        steps = [str(steps)]
    steps = [re.sub(r"^\s*(?:\d+[.)]|[-•*])\s*", "", str(s_)) for s_ in steps]
    steps = [s_ for s_ in steps if s_]

    answer = s("answer")
    if not answer and steps:
        answer = steps[-1]
    return AIAnswer({
        "what": s("what"),
        "steps": steps,
        "answer": answer,
        "hint": s("hint"),
        "similar": s("similar"),
        "provider": provider,
    })


def _quota_message(raw: str) -> str:
    """Достаёт из ответа 402 человеческую причину."""
    try:
        data = json.loads(raw)
        message = (data.get("error") or {}).get("message") or raw
    except Exception:  # noqa: BLE001
        message = raw
    return str(message).strip()[:200] or "на счету провайдера нет средств"


async def _post(url: str, payload: dict, headers: dict) -> dict:
    timeout = aiohttp.ClientTimeout(total=config.AI_TIMEOUT)
    last: Exception | None = None
    for attempt in range(2):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    raw = await resp.text()
                    if resp.status == 200:
                        return json.loads(raw)
                    if resp.status in (429,) and attempt == 0:
                        last = RateLimitError("HTTP 429")
                        await asyncio.sleep(1.0)
                        continue
                    if resp.status == 402:
                        raise QuotaError(_quota_message(raw))
                    if resp.status in (401, 403):
                        raise AuthError(f"ключ не принят (HTTP {resp.status})")
                    if resp.status == 429:
                        raise RateLimitError("лимит запросов у провайдера")
                    if resp.status == 404:
                        raise AIError("модель или адрес не найдены — проверь AI_MODEL и AI_BASE_URL")
                    raise AIError(f"провайдер ответил HTTP {resp.status}: {raw[:200]}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last = exc
            if attempt == 0:
                await asyncio.sleep(1.0)
                continue
            raise AIError(f"сеть недоступна: {type(exc).__name__}") from exc
    raise AIError(f"не удалось получить ответ: {last}")


def build_messages(task: str | None, mode: str, subject: str, grade: int,
                   student: str | None, image: tuple[bytes, str] | None,
                   extra: str = "") -> list[dict]:
    text = _user_text(task, mode, subject, grade, student, extra)
    if image:
        data, mime = image
        b64 = base64.b64encode(data).decode()
        content: list | str = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]
    else:
        content = text
    return [
        {"role": "system", "content": "Ты аккуратный и доброжелательный школьный учитель. Отвечай только JSON."},
        {"role": "user", "content": content},
    ]


async def ask(task: str | None, *, grade: int, subject: str, mode: str = "explain",
              student: str | None = None, image: tuple[bytes, str] | None = None,
              extra: str = "") -> AIAnswer:
    if config.AI_FORCE_MOCK:
        return _mock(task, mode, subject, grade)
    if not POOL.size:
        raise AIUnavailable("ключи AI не заданы")

    payload = {
        "model": config.AI_MODEL,
        "messages": build_messages(task, mode, subject, grade, student, image, extra),
        "temperature": config.AI_TEMPERATURE,
        "max_tokens": config.AI_MAX_TOKENS,
    }

    tried: set[str] = set()
    last_error: Exception | None = None
    for _ in range(POOL.size):
        key = POOL.take(exclude=tried)
        if key is None:
            break
        tried.add(key)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            data = await _post(f"{config.AI_BASE_URL}/chat/completions", payload, headers)
        except QuotaError as exc:
            # ключ верный, кончились деньги: не выключаем его, а говорим причину
            global _QUOTA_NOTE
            _QUOTA_NOTE = str(exc)
            raise
        except AuthError as exc:
            POOL.mark_dead(key, str(exc))
            last_error = exc
            continue
        except RateLimitError as exc:
            POOL.mark_soft(key)
            last_error = exc
            continue
        except AIError as exc:
            POOL.mark_fail(key)
            last_error = exc
            raise
        POOL.mark_ok(key)
        return _parse(data)

    if not POOL.has_alive():
        raise AIUnavailable("все ключи выключены: " + (str(last_error) if last_error else "нет ответа"))
    raise AIError(f"ключи не ответили: {last_error}")


def _parse(data: dict) -> AIAnswer:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("провайдер вернул неожиданный формат ответа") from exc
    if isinstance(content, list):
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))

    parsed = _extract_json(content)
    if parsed is None:
        log.warning("AI вернул не-JSON, показываю как текст")
        return AIAnswer({"what": "", "steps": [content.strip()[:1500]], "answer": "",
                         "hint": "", "similar": "", "provider": "ai-text"})
    if parsed.get("error"):
        raise AIError(str(parsed["error"])[:200])
    return _normalize(parsed, "ai")


def _mock(task: str | None, mode: str, subject: str, grade: int) -> AIAnswer:
    """Детерминированный ответ для тестов и демо без ключа."""
    base = task or "задание с фото"
    return AIAnswer({
        "what": f"Задание: {base[:80]}",
        "steps": [f"Шаг 1: разбираем условие ({subject}, {grade} класс).",
                  "Шаг 2: применяем правило.",
                  "Шаг 3: проверяем результат."],
        "answer": "42",
        "hint": "Проверь, сходится ли ответ с твоим.",
        "similar": "Похожая задача: 2 + 2 · 2.",
        "provider": f"mock-{mode}",
    })
