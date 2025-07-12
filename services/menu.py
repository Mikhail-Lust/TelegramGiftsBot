# --- Сторонние библиотеки ---
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Внутренние библиотеки ---
from services.config import get_valid_config, save_config, format_config_summary
from aiogram import Bot

async def update_last_menu_message_id(user_id: int, message_id: int) -> None:
    """
    Сохраняет id последнего сообщения с меню в конфиг пользователя.

    Args:
        user_id: ID пользователя.
        message_id: ID сообщения меню.
    """
    config = await get_valid_config(user_id)
    config["LAST_MENU_MESSAGE_ID"] = message_id
    await save_config(config, user_id)

async def get_last_menu_message_id(user_id: int) -> int | None:
    """
    Возвращает id последнего отправленного сообщения меню для пользователя.

    Args:
        user_id: ID пользователя.

    Returns:
        int | None: ID последнего сообщения меню или None.
    """
    config = await get_valid_config(user_id)
    return config.get("LAST_MENU_MESSAGE_ID")

def config_action_keyboard(active: bool) -> InlineKeyboardMarkup:
    """
    Генерирует inline-клавиатуру для меню с действиями.

    Args:
        active: Статус активности бота.

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками управления.
    """
    toggle_text = "🔴 Выключить" if active else "🟢 Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data="toggle_active"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data="profiles_menu")
        ],
        [
            InlineKeyboardButton(text="♻️ Сбросить", callback_data="reset_bought"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="show_help")
        ],
        [
            InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit_menu"),
            InlineKeyboardButton(text="↩️ Вывести", callback_data="refund_menu")
        ],
        [
            InlineKeyboardButton(text="🎏 Каталог подарков", callback_data="catalog")
        ]
    ])

async def update_menu(bot: Bot, chat_id: int, user_id: int, message_id: int = None) -> None:
    """
    Обновляет меню в чате: удаляет предыдущее и отправляет новое.

    Args:
        bot: Экземпляр бота.
        chat_id: ID чата.
        user_id: ID пользователя.
        message_id: ID сообщения для редактирования (опционально).
    """
    config = await get_valid_config(user_id)
    await delete_menu(bot=bot, chat_id=chat_id, user_id=user_id, current_message_id=message_id)
    await send_menu(bot=bot, chat_id=chat_id, user_id=user_id, config=config, text=format_config_summary(config, user_id))

async def delete_menu(bot: Bot, chat_id: int, user_id: int, current_message_id: int = None) -> None:
    """
    Удаляет последнее сообщение с меню, если оно отличается от текущего.

    Args:
        bot: Экземпляр бота.
        chat_id: ID чата.
        user_id: ID пользователя.
        current_message_id: ID текущего сообщения (опционально).
    """
    last_menu_message_id = await get_last_menu_message_id(user_id)
    if last_menu_message_id and last_menu_message_id != current_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=last_menu_message_id)
        except TelegramBadRequest as e:
            error_text = str(e)
            if "message can't be deleted for everyone" in error_text:
                await bot.send_message(
                    chat_id,
                    "⚠️ Предыдущее меню устарело и не может быть удалено (прошло более 48 часов). Используйте актуальное меню.\n"
                )
            elif "message to delete not found" in error_text:
                pass
            else:
                raise

async def send_menu(bot: Bot, chat_id: int, user_id: int, config: dict, text: str) -> int:
    """
    Отправляет новое меню в чат и обновляет id последнего сообщения.

    Args:
        bot: Экземпляр бота.
        chat_id: ID чата.
        user_id: ID пользователя.
        config: Конфигурация пользователя.
        text: Текст сообщения меню.

    Returns:
        int: ID отправленного сообщения.
    """
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=config_action_keyboard(config.get("ACTIVE"))
    )
    await update_last_menu_message_id(user_id, sent.message_id)
    return sent.message_id

def payment_keyboard(amount: int) -> InlineKeyboardMarkup:
    """
    Генерирует inline-клавиатуру с кнопкой оплаты для инвойса.

    Args:
        amount: Сумма для пополнения.

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой оплаты.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Пополнить ★{amount:,}", pay=True)
    return builder.as_markup()