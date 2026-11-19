"""Сборка роутеров. Порядок важен: платежи → проверка подписки → админка → разбор → общее."""
from aiogram import Router

from handlers import admin, common, pay, solve


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(pay.router)
    root.include_router(admin.router)        # публичная кнопка проверки подписки
    root.include_router(admin.admin_router)  # админка (только для ADMIN_IDS)
    root.include_router(solve.router)
    root.include_router(common.router)
    return root