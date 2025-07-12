from typing import Optional
from database import save_config as db_save_config, load_config, ensure_config
import logging

logger = logging.getLogger(__name__)

CURRENCY = 'XTR'
VERSION = '1.2.0'
DEV_MODE = False
MAX_PROFILES = 3
PURCHASE_COOLDOWN = 0.3

def DEFAULT_PROFILE(user_id: int) -> dict:
    return {
        "MIN_PRICE": 5000,
        "MAX_PRICE": 10000,
        "MIN_SUPPLY": 1000,
        "MAX_SUPPLY": 10000,
        "LIMIT": 1000000,
        "COUNT": 5,
        "TARGET_USER_ID": user_id,
        "TARGET_CHAT_ID": None,
        "BOUGHT": 0,
        "SPENT": 0,
        "DONE": False
    }

def DEFAULT_CONFIG(user_id: int) -> dict:
    return {
        "BALANCE": 0,
        "ACTIVE": False,
        "LAST_MENU_MESSAGE_ID": None,
        "PROFILES": [DEFAULT_PROFILE(user_id)]
    }

PROFILE_TYPES = {
    "MIN_PRICE": (int, False),
    "MAX_PRICE": (int, False),
    "MIN_SUPPLY": (int, False),
    "MAX_SUPPLY": (int, False),
    "LIMIT": (int, False),
    "COUNT": (int, False),
    "TARGET_USER_ID": (int, True),
    "TARGET_CHAT_ID": (str, True),
    "BOUGHT": (int, False),
    "SPENT": (int, False),
    "DONE": (bool, False),
}

CONFIG_TYPES = {
    "BALANCE": (int, False),
    "ACTIVE": (bool, False),
    "LAST_MENU_MESSAGE_ID": (int, True),
    "PROFILES": (list, False),
}

def is_valid_type(value, expected_type, allow_none=False):
    if value is None:
        return allow_none
    return isinstance(value, expected_type)

async def validate_profile(profile: dict, user_id: int) -> dict:
    valid = {}
    default = DEFAULT_PROFILE(user_id)
    for key, (expected_type, allow_none) in PROFILE_TYPES.items():
        if key not in profile or not is_valid_type(profile[key], expected_type, allow_none):
            valid[key] = default[key]
        else:
            valid[key] = profile[key]
    return valid

async def validate_config(config: dict, user_id: int) -> dict:
    valid = {}
    default = DEFAULT_CONFIG(user_id)
    for key, (expected_type, allow_none) in CONFIG_TYPES.items():
        if key == "PROFILES":
            profiles = config.get("PROFILES", [])
            valid_profiles = []
            for profile in profiles:
                valid_profiles.append(await validate_profile(profile, user_id))
            if not valid_profiles:
                valid_profiles = [DEFAULT_PROFILE(user_id)]
            valid["PROFILES"] = valid_profiles
        else:
            if key not in config or not is_valid_type(config[key], expected_type, allow_none):
                valid[key] = default[key]
            else:
                valid[key] = config[key]
    return valid

async def get_valid_config(user_id: int, path: str = None) -> dict:
    await ensure_config(user_id)
    config = await load_config(user_id)
    validated = await validate_config(config, user_id)
    if validated != config:
        await db_save_config(user_id, validated)
    return validated

async def save_config(config: dict, user_id: int) -> None:
    """
    Сохраняет конфигурацию пользователя в базу данных.

    Args:
        config: Конфигурация для сохранения.
        user_id: ID пользователя.
    """
    try:
        await db_save_config(user_id, config)
        logger.info(f"Конфигурация сохранена для user_id={user_id}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении конфигурации для user_id={user_id}: {e}")

async def add_profile(config: dict, profile: dict, user_id: int, save: bool = True) -> dict:
    config.setdefault("PROFILES", []).append(profile)
    if save:
        await save_config(config, user_id)
    return config

async def update_profile(config: dict, index: int, new_profile: dict, user_id: int, save: bool = True) -> dict:
    if "PROFILES" not in config or index >= len(config["PROFILES"]):
        raise IndexError("Профиль не найден")
    config["PROFILES"][index] = new_profile
    if save:
        await save_config(config, user_id)
    return config

async def remove_profile(config: dict, index: int, user_id: int, save: bool = True) -> dict:
    if "PROFILES" not in config or index >= len(config["PROFILES"]):
        raise IndexError("Профиль не найден")
    config["PROFILES"].pop(index)
    if not config["PROFILES"]:
        config["PROFILES"].append(DEFAULT_PROFILE(user_id))
    if save:
        await save_config(config, user_id)
    return config

def format_config_summary(config: dict, user_id: int) -> str:
    status_text = "🟢 Активен" if config.get("ACTIVE") else "🔴 Неактивен"
    balance = config.get("BALANCE", 0)
    profiles = config.get("PROFILES", [])
    lines = [f"🚦 <b>Статус:</b> {status_text}"]
    for idx, profile in enumerate(profiles, 1):
        target_display = get_target_display(profile, user_id)
        state_profile = (
            " ✅ <b>(завершён)</b>" if profile.get('DONE')
            else " ⚠️ <b>(частично)</b>" if profile.get('SPENT', 0) > 0
            else ""
        )
        line = (
            "\n"
            f"┌🔘 <b>Профиль {idx}</b>{state_profile}\n"
            f"├💰 <b>Цена</b>: {profile.get('MIN_PRICE'):,} – {profile.get('MAX_PRICE'):,} ★\n"
            f"├📦 <b>Саплай</b>: {profile.get('MIN_SUPPLY'):,} – {profile.get('MAX_SUPPLY'):,}\n"
            f"├🎁 <b>Куплено</b>: {profile.get('BOUGHT'):,} / {profile.get('COUNT'):,}\n"
            f"├⭐️ <b>Лимит</b>: {profile.get('SPENT'):,} / {profile.get('LIMIT'):,} ★\n"
            f"└👤 <b>Получатель</b>: {target_display}"
        )
        lines.append(line)
    lines.append(f"\n💰 <b>Баланс</b>: {balance:,} ★")
    return "\n".join(lines)

def get_target_display(profile: dict, user_id: int) -> str:
    target_chat_id = profile.get("TARGET_CHAT_ID")
    target_user_id = profile.get("TARGET_USER_ID")
    if target_chat_id:
        return f"{target_chat_id} (Канал)"
    elif str(target_user_id) == str(user_id):
        return f"<code>{target_user_id}</code> (Вы)"
    else:
        return f"<code>{target_user_id}</code>"

def get_target_display_local(target_user_id: int, target_chat_id: str, user_id: int) -> str:
    if target_chat_id:
        return f"{target_chat_id} (Канал)"
    elif str(target_user_id) == str(user_id):
        return f"<code>{target_user_id}</code> (Вы)"
    else:
        return f"<code>{target_user_id}</code>"