"""Пул API-ключей с ротацией: мёртвый ключ выключается, живой подхватывается сам.

Состояние хранится в data/keys_state.json (только хэши, не сами ключи).
Логика:
* ключ, вернувший 401/403, уходит в карантин на `DEAD_HOURS`;
* ключ, вернувший 429, остывает `SOFT_SECONDS`;
* успешный ключ становится приоритетным и запоминается на следующий запуск;
* если живых не осталось, пул честно говорит «нет ключей» — бот уходит в офлайн.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

log = logging.getLogger("keys")

DEAD_HOURS = 0.33  # 20 минут: ключ могли починить
SOFT_SECONDS = 90


def _h(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def mask(key: str) -> str:
    return f"{key[:7]}…{key[-4:]}" if len(key) > 14 else key


class KeyPool:
    def __init__(self, keys: list[str], state_path: Path | None = None):
        self._keys = list(dict.fromkeys(k.strip() for k in keys if k and k.strip()))
        self._state_path = state_path
        self._dead: dict[str, dict] = {}
        self._soft: dict[str, float] = {}
        self._fails: dict[str, int] = {}
        self._preferred: str | None = None
        self._idx = 0
        self._load()

    # --- состояние ---
    def _load(self) -> None:
        if not self._state_path or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        self._dead = {k: v for k, v in (data.get("dead") or {}).items() if isinstance(v, dict)}
        pref = data.get("preferred")
        if pref and any(_h(k) == pref for k in self._keys):
            self._preferred = pref

    def _save(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(
                {"dead": self._dead, "preferred": self._preferred},
                ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            log.warning("не смог сохранить состояние пула ключей")

    # --- выбор ключа ---
    def _is_dead(self, key: str) -> bool:
        info = self._dead.get(_h(key))
        if not info:
            return False
        if info.get("until", 0) > time.time():
            return True
        self._dead.pop(_h(key), None)
        return False

    def _is_soft(self, key: str) -> bool:
        until = self._soft.get(_h(key), 0)
        if until > time.time():
            return True
        self._soft.pop(_h(key), None)
        return False

    def alive(self) -> list[str]:
        return [k for k in self._keys if not self._is_dead(k) and not self._is_soft(k)]

    def has_alive(self) -> bool:
        return bool(self.alive())

    @property
    def size(self) -> int:
        return len(self._keys)

    def take(self, exclude: set[str] | None = None, include_dead: bool = False) -> str | None:
        """Следующий живой ключ по кругу. include_dead — принудительная перепроверка."""
        exclude = exclude or set()
        if include_dead:
            pool = [k for k in self._keys if k not in exclude]
        else:
            pool = [k for k in self.alive() if k not in exclude]
        if not pool:
            return None
        for k in pool:
            if _h(k) == self._preferred:
                return k
        key = pool[self._idx % len(pool)]
        self._idx += 1
        return key

    # --- обратная связь ---
    def mark_ok(self, key: str) -> None:
        self._fails.pop(_h(key), None)
        self._soft.pop(_h(key), None)
        self._dead.pop(_h(key), None)
        if self._preferred != _h(key):
            self._preferred = _h(key)
            log.info("ключ %s стал основным", mask(key))
            self._save()

    def mark_dead(self, key: str, reason: str = "") -> None:
        self._dead[_h(key)] = {"until": time.time() + DEAD_HOURS * 3600,
                               "reason": reason[:120], "mask": mask(key)}
        if self._preferred == _h(key):
            self._preferred = None
        log.warning("ключ %s отключён: %s", mask(key), reason or "ошибка авторизации")
        self._save()

    def mark_soft(self, key: str, seconds: float = SOFT_SECONDS) -> None:
        self._soft[_h(key)] = time.time() + seconds
        log.info("ключ %s остывает %.0f с", mask(key), seconds)

    def mark_fail(self, key: str) -> None:
        h = _h(key)
        self._fails[h] = self._fails.get(h, 0) + 1
        if self._fails[h] >= 3:
            self.mark_dead(key, "три ошибки подряд")

    def stats(self) -> dict:
        return {
            "total": len(self._keys),
            "alive": len(self.alive()),
            "dead": sum(1 for k in self._keys if self._is_dead(k)),
            "cooling": sum(1 for k in self._keys if self._is_soft(k)),
            "preferred": next((mask(k) for k in self._keys if _h(k) == self._preferred), "—"),
        }

    def last_reason(self) -> str:
        """Почему ключи отключены — чтобы показать человеку, а не молчать."""
        reasons = [info.get("reason", "") for info in self._dead.values() if info.get("reason")]
        if reasons:
            return reasons[-1]
        if self._keys:
            return "ключи проверяются при первом запросе"
        return "ключи не заданы"

    def report(self) -> str:
        st = self.stats()
        return (f"ключей: {st['total']} · живых: {st['alive']} · "
                f"в карантине: {st['dead']} · остывают: {st['cooling']} · "
                f"основной: {st['preferred']}")
