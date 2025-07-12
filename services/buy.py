# --- Стандартные библиотеки ---
import asyncio
import logging
import random

# --- Сторонние библиотеки ---
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter
from aiogram import Bot

# --- Внутренние модули ---
from services.config import get_valid_config, save_config, DEV_MODE
from services.balance import change_balance

logger = logging.getLogger(__name__)


async def buy_gift(
        bot: Bot,
        env_user_id: int,
        gift_id: str,
        user_id: int,
        chat_id: int,
        gift_price: int,
        file_id: str | None,
        retries: int = 3,
        add_test_purchases: bool = False
) -> bool:
    """
    Покупает подарок с заданными параметрами и количеством попыток.

    Args:
        bot: Экземпляр бота.
        env_user_id: ID пользователя из окружения (конфиг).
        gift_id: ID подарка.
        user_id: ID пользователя-получателя (может быть None).
        chat_id: ID чата-получателя (может быть None).
        gift_price: Стоимость подарка.
        file_id: ID файла (не используется в этой версии бота).
        retries: Количество попыток при ошибках.
        add_test_purchases: Включает тестовую логику покупки.

    Returns:
        bool: True, если покупка успешна, иначе False.
    """
    # Тестовая логика
    if add_test_purchases or DEV_MODE:
        result = random.choice([True, True, True, False])
        logger.info(f"[ТЕСТ] ({result}) Покупка подарка {gift_id} за {gift_price} (имитация, баланс не трогаем)")
        return result

    # Обычная логика
    config = await get_valid_config(env_user_id)
    balance = config["BALANCE"]
    if balance < gift_price:
        logger.error(f"Недостаточно звёзд для покупки подарка {gift_id} (требуется: {gift_price}, доступно: {balance})")
        config["ACTIVE"] = False
        await save_config(config, env_user_id)
        return False

    for attempt in range(1, retries + 1):
        try:
            if user_id is not None and chat_id is None:
                result = await bot.send_gift(gift_id=gift_id, user_id=user_id)
            elif user_id is None and chat_id is not None:
                result = await bot.send_gift(gift_id=gift_id, chat_id=chat_id)
            else:
                logger.error(f"Некорректные параметры: user_id={user_id}, chat_id={chat_id}")
                break

            if result:
                new_balance = await change_balance(bot, env_user_id, -gift_price)
                # Обновляем профиль
                config = await get_valid_config(env_user_id)
                config["PROFILES"][0]["BOUGHT"] = config["PROFILES"][0].get("BOUGHT", 0) + 1
                config["PROFILES"][0]["SPENT"] = config["PROFILES"][0].get("SPENT", 0) + gift_price
                await save_config(config, env_user_id)
                logger.info(f"Успешная покупка подарка {gift_id} за {gift_price} звёзд. Остаток: {new_balance}")
                return True

            logger.error(f"Попытка {attempt}/{retries}: Не удалось купить подарок {gift_id}. Повтор...")

        except TelegramRetryAfter as e:
            logger.error(f"Flood wait: ждём {e.retry_after} секунд")
            await asyncio.sleep(e.retry_after)

        except TelegramNetworkError as e:
            logger.error(f"Попытка {attempt}/{retries}: Сетевая ошибка: {e}. Повтор через {2 ** attempt} секунд...")
            await asyncio.sleep(2 ** attempt)

        except TelegramAPIError as e:
            logger.error(f"Ошибка Telegram API: {e}")
            break

    logger.error(f"Не удалось купить подарок {gift_id} после {retries} попыток.")
    return False