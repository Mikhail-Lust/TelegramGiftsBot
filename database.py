import aiosqlite
import json

DB_PATH = "bot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS configs (
                user_id INTEGER PRIMARY KEY,
                config TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.commit()

async def save_config(config: dict, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO configs (user_id, config) VALUES (?, ?)",
            (user_id, json.dumps(config))
        )
        await db.commit()

async def load_config(user_id: int) -> dict:
    from services.config import DEFAULT_CONFIG  # Ленивый импорт
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT config FROM configs WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return DEFAULT_CONFIG(user_id)

async def ensure_config(user_id: int):
    from services.config import DEFAULT_CONFIG  # Ленивый импорт
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM configs WHERE user_id = ?", (user_id,)) as cursor:
            if not await cursor.fetchone():
                await save_config(DEFAULT_CONFIG(user_id), user_id)

async def get_all_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM configs") as cursor:
            return [row[0] async for row in cursor]

async def add_allowed_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO allowed_users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def get_allowed_users():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM allowed_users") as cursor:
            return [row[0] async for row in cursor]

async def remove_allowed_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
        await db.commit()