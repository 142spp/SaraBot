import asyncpg

import config
from utils.logger import get_logger

logger = get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=5)
        logger.info("DB pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("DB pool closed")


async def init_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id          BIGSERIAL PRIMARY KEY,
                scope       TEXT NOT NULL,
                scope_id    BIGINT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_memories_scope
                ON memories (scope, scope_id);

            CREATE TABLE IF NOT EXISTS guild_configs (
                guild_id    BIGINT PRIMARY KEY,
                persona     TEXT,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
    logger.info("DB schema initialized")
