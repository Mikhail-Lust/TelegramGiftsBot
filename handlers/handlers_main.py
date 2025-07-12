# --- Сторонние библиотеки ---
from aiogram import F, Bot, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message, PreCheckoutQuery
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

# --- Внутренние модули ---
from services.config import get_valid_config, save_config, format_config_summary, get_target_display
from services.menu import update_menu, config_action_keyboard
from services.balance import refresh_balance, refund_all_star_payments
from services.buy import buy_gift
from database import add_allowed_user, remove_allowed_user, get_allowed_users
from dotenv import load_dotenv
import os

load_dotenv()
USER_ID = int(os.getenv("TELEGRAM_USER_ID"))  # ID админа из .env

router = Router()

def register_main_handlers(dp: Router, bot: Bot, version: str) -> None:
    """
    Регистрирует основные хендлеры для главного меню, стартовых и управляющих команд.
    """
    @dp.message(CommandStart())
    async def command_start_handler(message: Message, state: FSMContext) -> None:
        """
        Обрабатывает команду /start — обновляет баланс и показывает главное меню.
        Очищает все состояния FSM для пользователя.
        """
        user_id = message.from_user.id
        await state.clear()
        await refresh_balance(bot, user_id)
        await update_menu(bot=bot, chat_id=message.chat.id, user_id=user_id, message_id=message.message_id)

    @dp.message(Command("status"))
    async def command_status_handler(message: Message, state: FSMContext) -> None:
        """
        Обрабатывает команду /status — обновляет баланс и показывает текущую конфигурацию.
        """
        user_id = message.from_user.id
        await refresh_balance(bot, user_id)
        config = await get_valid_config(user_id)
        summary = format_config_summary(config, user_id)
        await message.answer(f"📊 Текущий статус:\n{summary}")

    @dp.message(Command("withdraw_all"))
    async def command_withdraw_all_handler(message: Message) -> None:
        """
        Обрабатывает команду /withdraw_all — запускает возврат всех звёзд.
        """
        user_id = message.from_user.id
        username = message.from_user.username
        if not username:
            await message.answer("⚠️ Для вывода средств нужен username в Telegram!")
            return
        result = await refresh_balance(bot, user_id)
        result = await refund_all_star_payments(bot, user_id, username, message_func=message.answer)
        refunded = result["refunded"]
        count = result["count"]
        left = result["left"]
        next_deposit = result["next_deposit"]
        text = f"💸 Возвращено: ★{refunded} ({count} транзакций)\n"
        if left > 0:
            text += f"📉 Остаток: ★{left}\n"
            if next_deposit:
                text += f"ℹ️ Для возврата остатка пополните баланс на ★{next_deposit['amount']} или больше."
            else:
                text += "ℹ️ Нет подходящих депозитов для возврата остатка."
        else:
            text += "✅ Весь баланс возвращён!"
        await message.answer(text)

    @dp.message(Command("grant_access"))
    async def command_grant_access_handler(message: Message) -> None:
        """
        Обрабатывает команду /grant_access — добавляет пользователя в список разрешённых.
        Доступно только админу.
        """
        user_id = message.from_user.id
        if user_id != USER_ID:
            await message.answer("⚠️ Эта команда доступна только администратору.")
            return
        args = message.text.split()
        if len(args) != 2:
            await message.answer("❌ Укажите ID пользователя: /grant_access <user_id>")
            return
        try:
            target_user_id = int(args[1])
            await add_allowed_user(target_user_id)
            await message.answer(f"✅ Пользователь {target_user_id} добавлен в список разрешённых.")
        except ValueError:
            await message.answer("❌ ID пользователя должен быть числом.")

    @dp.message(Command("revoke_access"))
    async def command_revoke_access_handler(message: Message) -> None:
        """
        Обрабатывает команду /revoke_access — удаляет пользователя из списка разрешённых.
        Доступно только админу.
        """
        user_id = message.from_user.id
        if user_id != USER_ID:
            await message.answer("⚠️ Эта команда доступна только администратору.")
            return
        args = message.text.split()
        if len(args) != 2:
            await message.answer("❌ Укажите ID пользователя: /revoke_access <user_id>")
            return
        try:
            target_user_id = int(args[1])
            if target_user_id == USER_ID:
                await message.answer("❌ Нельзя удалить доступ администратора.")
                return
            await remove_allowed_user(target_user_id)
            await message.answer(f"✅ Пользователь {target_user_id} удалён из списка разрешённых.")
        except ValueError:
            await message.answer("❌ ID пользователя должен быть числом.")

    @dp.message(Command("list_allowed_users"))
    async def command_list_allowed_users_handler(message: Message) -> None:
        """
        Обрабатывает команду /list_allowed_users — показывает список разрешённых пользователей.
        Доступно только админу.
        """
        user_id = message.from_user.id
        if user_id != USER_ID:
            await message.answer("⚠️ Эта команда доступна только администратору.")
            return
        allowed_users = await get_allowed_users()
        if not allowed_users:
            await message.answer("📋 Список разрешённых пользователей пуст.")
            return
        text = "📋 Разрешённые пользователи:\n" + "\n".join([f"- {uid}" for uid in allowed_users])
        await message.answer(text)

    @dp.callback_query(F.data == "main_menu")
    async def start_callback(call: CallbackQuery, state: FSMContext) -> None:
        """
        Показывает главное меню по нажатию кнопки "Вернуться в меню".
        Очищает все состояния FSM для пользователя.
        """
        user_id = call.from_user.id
        await state.clear()
        await call.answer()
        await refresh_balance(bot, user_id)
        await update_menu(
            bot=bot,
            chat_id=call.message.chat.id,
            user_id=user_id,
            message_id=call.message.message_id
        )

    @dp.callback_query(F.data == "show_help")
    async def help_callback(call: CallbackQuery) -> None:
        """
        Показывает подробную справку по работе с ботом.
        """
        user_id = call.from_user.id
        config = await get_valid_config(user_id)
        # По умолчанию первый профиль
        profile = config["PROFILES"][0]
        target_display = get_target_display(profile, user_id)
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        help_text = (
            f"<b>🛠 Управление ботом <code>v{version}</code> :</b>\n\n"
            "<b>🟢 Включить / 🔴 Выключить</b> — запускает или останавливает покупки.\n"
            "<b>✏️ Изменить</b> — Добавление и удаление профилей с конфигурациями для покупки подарков.\n"
            "<b>♻️ Сбросить счётчик</b> — обнуляет количество уже купленных подарков для всех профилей, чтобы не создавать снова такие же профили.\n"
            "<b>💰 Пополнить</b> — депозит звёзд в бот.\n"
            "<b>↩️ Вывести</b> — возврат звёзд по ID транзакции или вывести все звёзды сразу по команде /withdraw_all.\n"
            "<b>🎏 Каталог подарков</b> — список доступных к покупке подарков в маркете.\n\n"
            "<b>📌 Подсказки:</b>\n\n"
            f"❗️ Если получатель подарка — другой пользователь, он должен зайти в этот бот <code>@{bot_username}</code> и нажать <code>/start</code>.\n"
            "❗️ Получатель подарка <b>аккаунт</b> — пишите <b>id</b> пользователя (узнать id можно тут @userinfobot).\n"
            "❗️ Получатель подарка <b>канал</b> — пишите <b>username</b> канала.\n"
            f"❗️ Чтобы пополнить баланс бота с любого аккаунта, зайдите в этот бот <code>@{bot_username}</code> и нажмите <code>/start</code>, чтобы вызвать меню пополнения.\n"
            "❗️ Как посмотреть <b>ID транзакции</b> для возврата звёзд?  Нажмите на сообщение об оплате в чате с ботом и там будет ID транзакции.\n"
            f"❗️ Хотите протестировать бот? Купите подарок 🧸 за ★15, получатель {target_display}.\n\n"
        )
        button = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Тест? Купить 🧸 за ★15", callback_data="buy_test_gift")],
            [InlineKeyboardButton(text="☰ Вернуться в меню", callback_data="main_menu")]
        ])
        await call.answer()
        await call.message.answer(help_text, reply_markup=button)

    @dp.callback_query(F.data == "buy_test_gift")
    async def buy_test_gift(call: CallbackQuery) -> None:
        """
        Покупка тестового подарка для проверки работы бота.
        """
        user_id = call.from_user.id
        gift_id = '5170233102089322756'
        config = await get_valid_config(user_id)
        # Используем первый профиль по умолчанию
        profile = config["PROFILES"][0]
        TARGET_USER_ID = profile["TARGET_USER_ID"]
        TARGET_CHAT_ID = profile["TARGET_CHAT_ID"]
        target_display = get_target_display(profile, user_id)

        success = await buy_gift(
            bot=bot,
            env_user_id=user_id,
            gift_id=gift_id,
            user_id=TARGET_USER_ID,
            chat_id=TARGET_CHAT_ID,
            gift_price=15,
            file_id=None
        )
        if not success:
            await call.answer()
            await call.message.answer("⚠️ Покупка подарка 🧸 за ★15 невозможна.\n💰 Пополните баланс.\n🚦 Статус изменён на 🔴 (неактивен).")
            config["ACTIVE"] = False
            await save_config(config, user_id)
            await update_menu(bot=bot, chat_id=call.message.chat.id, user_id=user_id, message_id=call.message.message_id)
            return

        await call.answer()
        await call.message.answer(f"✅ Подарок 🧸 за ★15 куплен. Получатель: {target_display}.")
        await update_menu(bot=bot, chat_id=call.message.chat.id, user_id=user_id, message_id=call.message.message_id)

    @dp.callback_query(F.data == "reset_bought")
    async def reset_bought_callback(call: CallbackQuery) -> None:
        """
        Сброс счетчиков купленных подарков и статусов выполнения по всем профилям.
        """
        user_id = call.from_user.id
        config = await get_valid_config(user_id)
        # Сбросить счетчики во всех профилях
        for profile in config["PROFILES"]:
            profile["BOUGHT"] = 0
            profile["SPENT"] = 0
            profile["DONE"] = False
        config["ACTIVE"] = False
        await save_config(config, user_id)
        info = format_config_summary(config, user_id)
        try:
            await call.message.edit_text(
                info,
                reply_markup=config_action_keyboard(config["ACTIVE"])
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        await call.answer("Счётчик покупок сброшен.")

    @dp.callback_query(F.data == "toggle_active")
    async def toggle_active_callback(call: CallbackQuery) -> None:
        """
        Переключение статуса работы бота: активен/неактивен.
        """
        user_id = call.from_user.id
        config = await get_valid_config(user_id)
        config["ACTIVE"] = not config.get("ACTIVE", False)
        await save_config(config, user_id)
        info = format_config_summary(config, user_id)
        await call.message.edit_text(
            info,
            reply_markup=config_action_keyboard(config["ACTIVE"])
        )
        await call.answer("Статус обновлён")

    @dp.pre_checkout_query()
    async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery) -> None:
        """
        Обработка предоплаты в Telegram Invoice.
        """
        await pre_checkout_query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def process_successful_payment(message: Message) -> None:
        """
        Обработка успешного пополнения баланса через Telegram Invoice.
        """
        user_id = message.from_user.id
        await message.answer(
            f'✅ Баланс успешно пополнен.',
            message_effect_id="5104841245755180586"
        )
        await refresh_balance(bot, user_id)
        await update_menu(bot=bot, chat_id=message.chat.id, user_id=user_id, message_id=message.message_id)