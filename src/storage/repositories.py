from storage.db import get_pool
from utils.logger import get_logger

logger = get_logger(__name__)


class MemoryRepository:
    async def save(self, scope: str, scope_id: int, content: str) -> int:
        pool = await get_pool()
        row = await pool.fetchrow(
            "INSERT INTO memories (scope, scope_id, content) VALUES ($1, $2, $3) RETURNING id",
            scope, scope_id, content,
        )
        memory_id = row["id"]
        logger.debug(f"Memory saved: id={memory_id} scope={scope}/{scope_id}")
        return memory_id

    async def delete(self, scope: str, scope_id: int, memory_id: int) -> bool:
        pool = await get_pool()
        result = await pool.execute(
            "DELETE FROM memories WHERE id=$1 AND scope=$2 AND scope_id=$3",
            memory_id, scope, scope_id,
        )
        deleted = result.split()[-1] == "1"
        logger.debug(f"Memory delete: id={memory_id} deleted={deleted}")
        return deleted

    async def list(self, scope: str, scope_id: int) -> list[dict]:
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT id, content, created_at FROM memories "
            "WHERE scope=$1 AND scope_id=$2 ORDER BY created_at DESC",
            scope, scope_id,
        )
        return [{"id": r["id"], "content": r["content"]} for r in rows]


class GuildConfigRepository:
    async def get_persona(self, guild_id: int) -> str | None:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT persona FROM guild_configs WHERE guild_id=$1", guild_id
        )
        return row["persona"] if row else None

    async def set_persona(self, guild_id: int, persona: str) -> None:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO guild_configs (guild_id, persona, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (guild_id) DO UPDATE
                SET persona=EXCLUDED.persona, updated_at=NOW()
            """,
            guild_id, persona,
        )
