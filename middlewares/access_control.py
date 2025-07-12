from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from database import get_allowed_users

class AccessControlMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        allowed_user_ids = await get_allowed_users()  # Динамически получаем список из базы
        if user and user.id in allowed_user_ids:
            return await handler(event, data)
        # Разрешаем гостевые операции (пополнение/вывод) для всех
        if hasattr(event, "message") and event.message.text in ["/deposit", "/withdraw"]:
            return await handler(event, data)
        await event.answer("⚠️ Доступ запрещён. Обратитесь к администратору.")
        return