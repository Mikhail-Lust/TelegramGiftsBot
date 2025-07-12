# --- Стандартные библиотеки ---
from itertools import combinations
import logging

# --- Внутренние модули ---
from services.config import get_valid_config, save_config
from aiogram import Bot

logger = logging.getLogger(__name__)

async def get_stars_balance(bot: Bot, user_id: int) -> int:
    """
    Получает суммарный баланс звёзд по транзакциям пользователя через API бота.

    Args:
        bot: Экземпляр бота.
        user_id: ID пользователя.

    Returns:
        int: Текущий баланс пользователя.
    """
    offset = 0
    limit = 100
    balance = 0

    while True:
        try:
            get_transactions = await bot.get_star_transactions(offset=offset, limit=limit)
            transactions = get_transactions.transactions

            if not transactions:
                break

            for transaction in transactions:
                source = transaction.source
                amount = transaction.amount
                # Проверяем, что транзакция связана с user_id
                if source and getattr(source, "user", None) and source.user.id == user_id:
                    balance += amount
                elif source is None:  # Возвраты, связанные с user_id
                    balance -= amount

            offset += limit
        except Exception as e:
            logger.error(f"Ошибка при получении транзакций для user_id={user_id}: {e}")
            break

    logger.info(f"Получен баланс для user_id={user_id}: {balance}")
    return balance

async def refresh_balance(bot: Bot, user_id: int) -> int:
    """
    Обновляет и сохраняет баланс звёзд в конфиге пользователя, возвращает актуальное значение.

    Args:
        bot: Экземпляр бота.
        user_id: ID пользователя.

    Returns:
        int: Текущий баланс.
    """
    try:
        balance = await get_stars_balance(bot, user_id)
        config = await get_valid_config(user_id)
        config["BALANCE"] = balance
        await save_config(config, user_id)
        logger.info(f"Баланс обновлён для user_id={user_id}: {balance}")
        return balance
    except Exception as e:
        logger.error(f"Ошибка при обновлении баланса для user_id={user_id}: {e}")
        config = await get_valid_config(user_id)
        return config.get("BALANCE", 0)

async def change_balance(bot: Bot, user_id: int, delta: int) -> int:
    """
    Изменяет баланс звёзд в конфиге пользователя на указанное значение delta, не допуская отрицательных значений.

    Args:
        bot: Экземпляр бота.
        user_id: ID пользователя.
        delta: Изменение баланса (положительное или отрицательное).

    Returns:
        int: Новый баланс.
    """
    try:
        config = await get_valid_config(user_id)
        config["BALANCE"] = max(0, config.get("BALANCE", 0) + delta)
        balance = config["BALANCE"]
        await save_config(config, user_id)
        logger.info(f"Баланс изменён для user_id={user_id}: {balance}")
        return balance
    except Exception as e:
        logger.error(f"Ошибка при изменении баланса для user_id={user_id}: {e}")
        config = await get_valid_config(user_id)
        return config.get("BALANCE", 0)

async def refund_all_star_payments(bot: Bot, user_id: int, username: str, message_func=None) -> dict:
    """
    Возвращает звёзды только по депозитам без возврата, совершённым указанным username.
    Подбирает оптимальную комбинацию для вывода максимально возможной суммы.

    Args:
        bot: Экземпляр бота.
        user_id: ID пользователя.
        username: Имя пользователя, чьи депозиты возвращаются.
        message_func: Функция для отправки сообщений (опционально).

    Returns:
        dict: Результат возврата с полями "refunded", "count", "txn_ids", "left", "next_deposit".
    """
    try:
        balance = await refresh_balance(bot, user_id)
        if balance <= 0:
            logger.info(f"Баланс user_id={user_id} равен 0, возврат не требуется")
            return {"refunded": 0, "count": 0, "txn_ids": [], "left": 0, "next_deposit": None}

        # Получаем все транзакции
        offset = 0
        limit = 100
        all_txns = []
        while True:
            try:
                res = await bot.get_star_transactions(offset=offset, limit=limit)
                txns = res.transactions
                if not txns:
                    break
                all_txns.extend(txns)
                offset += limit
            except Exception as e:
                logger.error(f"Ошибка при получении транзакций для user_id={user_id}: {e}")
                break

        # Фильтруем депозиты без возврата и только с нужным username
        deposits = [
            t for t in all_txns
            if t.source is not None
            and getattr(t.source, "user", None)
            and getattr(t.source.user, "username", None) == username
            and getattr(t.source.user, "id", None) == user_id
        ]
        refunded_ids = {t.id for t in all_txns if t.source is None}
        unrefunded_deposits = [t for t in deposits if t.id not in refunded_ids]

        n = len(unrefunded_deposits)
        best_combo = []
        best_sum = 0

        # Ищем идеальную комбинацию или greedy
        if n <= 18:
            for r in range(1, n + 1):
                for combo in combinations(unrefunded_deposits, r):
                    s = sum(t.amount for t in combo)
                    if s <= balance and s > best_sum:
                        best_combo = combo
                        best_sum = s
                    if best_sum == balance:
                        break
                if best_sum == balance:
                    break
        else:
            unrefunded_deposits.sort(key=lambda t: t.amount, reverse=True)
            curr_sum = 0
            best_combo = []
            for t in unrefunded_deposits:
                if curr_sum + t.amount <= balance:
                    best_combo.append(t)
                    curr_sum += t.amount
            best_sum = curr_sum

        if not best_combo:
            logger.info(f"Нет подходящих депозитов для возврата для user_id={user_id}")
            return {"refunded": 0, "count": 0, "txn_ids": [], "left": balance, "next_deposit": None}

        # Делаем возвраты только по выбранным транзакциям
        total_refunded = 0
        refund_ids = []
        for txn in best_combo:
            txn_id = getattr(txn, "id", None)
            if not txn_id:
                continue
            try:
                await bot.refund_star_payment(
                    user_id=user_id,
                    telegram_payment_charge_id=txn_id
                )
                total_refunded += txn.amount
                refund_ids.append(txn_id)
                logger.info(f"Возврат {txn.amount} звёзд для user_id={user_id}, txn_id={txn_id}")
            except Exception as e:
                logger.error(f"Ошибка при возврате {txn.amount} звёзд для user_id={user_id}: {e}")
                if message_func:
                    await message_func(f"🚫 Ошибка при возврате ★{txn.amount}")

        left = balance - total_refunded

        # Находим транзакцию, которой хватит чтобы покрыть остаток
        def find_next_possible_deposit(unused_deposits, min_needed):
            bigger = [t for t in unused_deposits if t.amount > min_needed]
            if not bigger:
                return None
            best = min(bigger, key=lambda t: t.amount)
            return {"amount": best.amount, "id": getattr(best, "id", None)}

        unused_deposits = [t for t in unrefunded_deposits if t not in best_combo]
        next_possible = None
        if left > 0 and unused_deposits:
            next_possible = find_next_possible_deposit(unused_deposits, left)

        return {
            "refunded": total_refunded,
            "count": len(refund_ids),
            "txn_ids": refund_ids,
            "left": left,
            "next_deposit": next_possible
        }
    except Exception as e:
        logger.error(f"Ошибка при возврате платежей для user_id={user_id}: {e}")
        return {"refunded": 0, "count": 0, "txn_ids": [], "left": balance, "next_deposit": None}