import asyncpg

import config
from utils.logger import get_logger

logger = get_logger(__name__)

_pool: asyncpg.Pool | None = None
_ro_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=5)
        logger.info("DB pool created")
    return _pool


async def get_ro_pool() -> asyncpg.Pool:
    """읽기 전용 계정(sachiko_ro) 풀 — run_sql 툴 전용."""
    global _ro_pool
    if _ro_pool is None:
        _ro_pool = await asyncpg.create_pool(
            config.DATABASE_URL_RO, min_size=1, max_size=3
        )
        logger.info("RO DB pool created")
    return _ro_pool


async def close_pool() -> None:
    global _pool, _ro_pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("DB pool closed")
    if _ro_pool:
        await _ro_pool.close()
        _ro_pool = None
        logger.info("RO DB pool closed")


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

            CREATE TABLE IF NOT EXISTS user_affinity (
                guild_id    BIGINT NOT NULL,
                user_id     BIGINT NOT NULL,
                score       INT NOT NULL DEFAULT 50,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                message_id  BIGINT PRIMARY KEY,
                channel_id  BIGINT NOT NULL,
                guild_id    BIGINT NOT NULL,
                author_id   BIGINT NOT NULL,
                author_name TEXT NOT NULL,
                content     TEXT,
                is_bot      BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMPTZ NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_channel_created
                ON messages (channel_id, created_at);

            CREATE TABLE IF NOT EXISTS message_chunks (
                id           BIGSERIAL PRIMARY KEY,
                channel_id   BIGINT NOT NULL,
                guild_id     BIGINT NOT NULL,
                start_msg_id BIGINT NOT NULL,
                end_msg_id   BIGINT NOT NULL,
                start_at     TIMESTAMPTZ NOT NULL,
                end_at       TIMESTAMPTZ NOT NULL,
                authors      TEXT,
                content      TEXT NOT NULL,
                embedding    vector(1536)
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_channel_end
                ON message_chunks (channel_id, end_msg_id);

            CREATE TABLE IF NOT EXISTS message_chunk_search_docs (
                id             BIGSERIAL PRIMARY KEY,
                guild_id       BIGINT NOT NULL,
                channel_id     BIGINT NOT NULL,
                start_chunk_id BIGINT NOT NULL,
                end_chunk_id   BIGINT NOT NULL,
                start_msg_id   BIGINT NOT NULL,
                end_msg_id     BIGINT NOT NULL,
                start_at       TIMESTAMPTZ NOT NULL,
                end_at         TIMESTAMPTZ NOT NULL,
                authors        TEXT,
                source_content TEXT NOT NULL,
                search_text    TEXT NOT NULL,
                embedding      vector(1536),
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_search_docs_channel_end
                ON message_chunk_search_docs (channel_id, end_msg_id);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_search_docs_chunk_range
                ON message_chunk_search_docs (start_chunk_id, end_chunk_id);
        """)
    logger.info("DB schema initialized")
