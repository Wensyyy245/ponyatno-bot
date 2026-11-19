"""Определение папки для данных: проект → LOCALAPPDATA → TEMP.

Windows часто не даёт писать в папку проекта (запуск из другого каталога,
защищённый путь, OneDrive, антивирус). Бот не должен из-за этого падать.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _local_appdata() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        return Path(base) / "Ponyatno"
    return Path.home() / "AppData" / "Local" / "Ponyatno"


def resolve(preferred: Path) -> tuple[Path, str]:
    """Возвращает (папка, пояснение) — первую, куда реально можно писать."""
    candidates = [
        (Path(preferred), "папка проекта"),
        (_local_appdata(), "локальные данные пользователя"),
        (Path(tempfile.gettempdir()) / "Ponyatno", "временная папка"),
    ]
    for path, note in candidates:
        if writable(path):
            return path, note
    return Path(tempfile.gettempdir()), "временная папка (без проверки записи)"
