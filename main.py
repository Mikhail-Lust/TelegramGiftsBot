# --- Стандартные библиотеки ---
import asyncio
import logging
import os
import sys

# --- Сторонние библиотеки ---
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# --- Внутренние модули ---
from services.config import (
    ensure_config,
    save_config,
    get_valid_config,
    get_target_display,
    DEFAULT_CONFIG,
    VERSION,
    PURCHASE_COOLDOWN
)
from services.menu import update_menu
from services.balance import refresh_balance
from services.gifts import get_filtered_gifts
from services.buy import buy_gift
from handlers.handlers_wizard import register_wizard_handlers
from handlers.handlers_catalog import register_catalog_handlers
from handlers.handlers_main import register_main_handlers
from utils.logging import setup_logging
from middlewares.access_control import AccessControlMiddleware
from middlewares.rate_limit import RateLimitMiddleware
from database import init_db, get_allowed_users, add_allowed_user

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USER_ID = int(os.getenv("TELEGRAM_USER_ID"))

setup_logging()
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.message.middleware(RateLimitMiddleware(commands_limits={"/start": 3, "/withdraw_all": 3, "/grant_access": 3, "/revoke_access": 3}))
dp.message.middleware(AccessControlMiddleware())
dp.callback_query.middleware(AccessControlMiddleware())

register_wizard_handlers(dp)
register_catalog_handlers(dp)
register_main_handlers(
    dp=dp,
    bot=bot,
    version=VERSION
)

async def gift_purchase_worker():
    """
    Фоновый воркер для покупки подарков по профилям всех разрешённых пользователей.
    Учитывает параметр LIMIT — максимальную сумму звёзд, которую можно потратить на профиль.
    Если лимит исчерпан — профиль считается завершённым и воркер переходит к следующему.
    """
    while True:
        try:
            allowed_user_ids = await get_allowed_users()  # Получаем список разрешённых пользователей
            for user_id in allowed_user_ids:
                config = await get_valid_config(user_id)
                if not config["ACTIVE"]:
                    continue

                message = None
                report_message_lines = []
                progress_made = False  # Был ли прогресс по профилям на этом проходе
                any_success = True

                for profile_index, profile in enumerate(config["PROFILES"]):
                    # Пропускаем завершённые профили
                    if profile.get("DONE"):
                        continue

                    MIN_PRICE = profile["MIN_PRICE"]
                    MAX_PRICE = profile["MAX_PRICE"]
                    MIN_SUPPLY = profile["MIN_SUPPLY"]
                    MAX_SUPPLY = profile["MAX_SUPPLY"]
                    COUNT = profile["COUNT"]
                    LIMIT = profile.get("LIMIT", 0)
                    TARGET_USER_ID = profile["TARGET_USER_ID"]
                    TARGET_CHAT_ID = profile["TARGET_CHAT_ID"]

                    filtered_gifts = await get_filtered_gifts(
                        bot, MIN_PRICE, MAX_PRICE, MIN_SUPPLY, MAX_SUPPLY
                    )

                    if not filtered_gifts:
                        continue

                    purchases = []
                    before_bought = profile["BOUGHT"]
                    before_spent = profile["SPENT"]

                    for gift in filtered_gifts:
                        gift_id = gift["id"]
                        gift_price = gift["price"]
                        gift_total_count = gift["supply"]
                        sticker_file_id = gift["sticker_file_id"]

                        # Проверяем лимит перед каждой покупкой
                        while (profile["BOUGHT"] < COUNT and
                               profile["SPENT"] + gift_price <= LIMIT):
                            success = await buy_gift(
                                bot=bot,
                                env_user_id=user_id,  # Используем user_id вместо USER_ID
                                gift_id=gift_id,
                                user_id=TARGET_USER_ID,
                                chat_id=TARGET_CHAT_ID,
                                gift_price=gift_price,
                                file_id=sticker_file_id
                            )

                            if not success:
                                any_success = False
                                break  # Не удалось купить — пробуем следующий подарок

                            config = await get_valid_config(user_id)
                            profile = config["PROFILES"][profile_index]
                            profile["BOUGHT"] += 1
                            profile["SPENT"] += gift_price
                            purchases.append({"id": gift_id, "price": gift_price})
                            await save_config(config, user_id)
                            await asyncio.sleep(PURCHASE_COOLDOWN)

                            # Проверяем: не достигли ли лимит после покупки
                            if profile["SPENT"] >= LIMIT:
                                break

                        if profile["BOUGHT"] >= COUNT or profile["SPENT"] >= LIMIT:
                            break  # Достигли лимит либо по количеству, либо по сумме

                    after_bought = profile["BOUGHT"]
                    after_spent = profile["SPENT"]
                    made_local_progress = (after_bought > before_bought) or (after_spent > before_spent)

                    # Профиль полностью выполнен: либо по количеству, либо по лимиту
                    if (profile["BOUGHT"] >= COUNT or profile["SPENT"] >= LIMIT) and not profile["DONE"]:
                        config = await get_valid_config(user_id)
                        profile = config["PROFILES"][profile_index]
                        profile["DONE"] = True
                        await save_config(config, user_id)

                        target_display = get_target_display(profile, user_id)
                        summary_lines = [
                            f"\n┌✅ <b>Профиль {profile_index+1}</b>\n"
                            f"├👤 <b>Получатель:</b> {target_display}\n"
                            f"├💸 <b>Потрачено:</b> {profile['SPENT']:,} / {LIMIT:,} ★\n"
                            f"└🎁 <b>Куплено </b>{profile['BOUGHT']} из {COUNT}:"
                        ]
                        gift_summary = {}
                        for p in purchases:
                            key = p["id"]
                            if key not in gift_summary:
                                gift_summary[key] = {"price": p["price"], "count": 0}
                            gift_summary[key]["count"] += 1

                        gift_items = list(gift_summary.items())
                        for idx, (gid, data) in enumerate(gift_items):
                            prefix = "   └" if idx == len(gift_items) - 1 else "   ├"
                            summary_lines.append(
                                f"{prefix} {data['price']:,} ★ × {data['count']}"
                            )
                        report_message_lines += summary_lines

                        logger.info(f"Профиль #{profile_index+1} завершён для user_id={user_id}")
                        progress_made = True
                        await refresh_balance(bot, user_id)  # Передаём user_id
                        continue  # К следующему профилю

                    # Если ничего не куплено — баланс/лимит/подарки кончились
                    if (profile["BOUGHT"] < COUNT or profile["SPENT"] < LIMIT) and not profile["DONE"] and made_local_progress:
                        target_display = get_target_display(profile, user_id)
                        summary_lines = [
                            f"\n┌⚠️ <b>Профиль {profile_index+1}</b> (частично)\n"
                            f"├👤 <b>Получатель:</b> {target_display}\n"
                            f"├💸 <b>Потрачено:</b> {profile['SPENT']:,} / {LIMIT:,} ★\n"
                            f"└🎁 <b>Куплено </b>{profile['BOUGHT']} из {COUNT}:"
                        ]
                        gift_summary = {}
                        for p in purchases:
                            key = p["id"]
                            if key not in gift_summary:
                                gift_summary[key] = {"price": p["price"], "count": 0}
                            gift_summary[key]["count"] += 1

                        gift_items = list(gift_summary.items())
                        for idx, (gid, data) in enumerate(gift_items):
                            prefix = "   └" if idx == len(gift_items) - 1 else "   ├"
                            summary_lines.append(
                                f"{prefix} {data['price']:,} ★ × {data['count']}"
                            )
                        report_message_lines += summary_lines

                        logger.warning(f"Профиль #{profile_index+1} не завершён для user_id={user_id}")
                        progress_made = True
                        await refresh_balance(bot, user_id)  # Передаём user_id
                        continue  # К следующему профилю

                if not any_success and not progress_made:
                    logger.warning(
                        f"Не удалось купить ни один подарок ни в одном профиле для user_id={user_id}"
                    )
                    config["ACTIVE"] = False
                    await save_config(config, user_id)
                    text = "⚠️ Найдены подходящие подарки, но <b>не удалось</b> купить.\n💰 Пополните баланс!\n🚦 Статус изменён на 🔴 (неактивен)."
                    message = await bot.send_message(chat_id=user_id, text=text)
                    await update_menu(
                        bot=bot, chat_id=user_id, user_id=user_id, message_id=message.message_id
                    )

                # После обработки всех профилей:
                if progress_made:
                    config["ACTIVE"] = not all(p.get("DONE") for p in config["PROFILES"])
                    await save_config(config, user_id)
                    logger.info(f"Отчёт: хотя бы один профиль обработан для user_id={user_id}")
                    text = "🍀 <b>Отчёт по профилям:</b>\n"
                    text += "\n".join(report_message_lines) if report_message_lines else "⚠️ Покупок не совершено."
                    message = await bot.send_message(chat_id=user_id, text=text)
                    await update_menu(
                        bot=bot, chat_id=user_id, user_id=user_id, message_id=message.message_id
                    )

                if all(p.get("DONE") for p in config["PROFILES"]) and config["ACTIVE"]:
                    config["ACTIVE"] = False
                    await save_config(config, user_id)
                    text = "✅ Все профили <b>завершены</b>!\n⚠️ Нажмите ♻️ <b>Сбросить</b> или ✏️ <b>Изменить</b>!"
                    message = await bot.send_message(chat_id=user_id, text=text)
                    await update_menu(
                        bot=bot, chat_id=user_id, user_id=user_id, message_id=message.message_id
                    )

        except Exception as e:
            logger.error(f"Ошибка в gift_purchase_worker для user_id={user_id}: {e}")

        await asyncio.sleep(0.5)

async def main() -> None:
    """
    Точка входа: инициализация базы данных, добавление админа, запуск воркера и polling.
    """
    logger.info("Бот запущен!")
    await init_db()  # Инициализация базы данных
    await add_allowed_user(USER_ID)  # Добавляем админа в список разрешённых
    await ensure_config(USER_ID)  # Создаём конфиг для админа
    asyncio.create_task(gift_purchase_worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())