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


class MessageRepository:
    async def bulk_upsert(self, rows: list[tuple]) -> None:
        """rows: (message_id, channel_id, guild_id, author_id, author_name, content, is_bot, created_at)"""
        if not rows:
            return
        pool = await get_pool()
        await pool.executemany(
            """
            INSERT INTO messages
                (message_id, channel_id, guild_id, author_id, author_name, content, is_bot, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (message_id) DO NOTHING
            """,
            rows,
        )

    async def latest_message_id(self, channel_id: int) -> int | None:
        """증분 적재용 — 해당 채널에 저장된 가장 최신 message_id (snowflake는 시간순 증가)."""
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT message_id FROM messages WHERE channel_id=$1 "
            "ORDER BY message_id DESC LIMIT 1",
            channel_id,
        )
        return row["message_id"] if row else None

    async def count_by_channel(self, channel_id: int) -> int:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT count(*) AS c FROM messages WHERE channel_id=$1", channel_id
        )
        return row["c"]

    async def messages_after(
        self, channel_id: int, after_msg_id: int | None
    ) -> list:
        """청킹용 — 특정 message_id 이후(없으면 전체) 메시지를 message_id 오름차순 반환."""
        pool = await get_pool()
        if after_msg_id:
            return await pool.fetch(
                "SELECT message_id, author_name, content, created_at FROM messages "
                "WHERE channel_id=$1 AND message_id > $2 ORDER BY message_id ASC",
                channel_id, after_msg_id,
            )
        return await pool.fetch(
            "SELECT message_id, author_name, content, created_at FROM messages "
            "WHERE channel_id=$1 ORDER BY message_id ASC",
            channel_id,
        )

    async def search(
        self,
        guild_id: int,
        terms: list[str],
        author: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """content에 terms를 모두(AND) 포함하는 메시지를 최신순으로 반환 (서버 전체).

        author가 주어지면 작성자 이름(부분일치)으로도 필터링한다.
        """
        pool = await get_pool()
        conditions = ["guild_id = $1"]
        params: list = [guild_id]
        if author:
            params.append(f"%{author}%")
            conditions.append(f"author_name ILIKE ${len(params)}")
        for term in terms:
            params.append(f"%{term}%")
            conditions.append(f"content ILIKE ${len(params)}")
        params.append(limit)
        sql = (
            "SELECT author_name, content, is_bot, created_at FROM messages "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY created_at DESC LIMIT ${len(params)}"
        )
        rows = await pool.fetch(sql, *params)
        return [
            {
                "author": r["author_name"],
                "is_bot": r["is_bot"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]


    async def sample_by_author(
        self, guild_id: int, author: str, recent: int = 50, even: int = 250
    ) -> list[dict]:
        """작성자의 메시지를 '최신 recent개 + 전 기간 균등 even개'로 뽑아 시간순 반환 (서버 전체)."""
        pool = await get_pool()
        author_like = f"%{author}%"

        recent_rows = await pool.fetch(
            "SELECT message_id, author_name, content, is_bot, created_at FROM messages "
            "WHERE guild_id=$1 AND author_name ILIKE $2 "
            "ORDER BY created_at DESC LIMIT $3",
            guild_id, author_like, recent,
        )

        even_rows = await pool.fetch(
            """
            WITH ranked AS (
                SELECT message_id, author_name, content, is_bot, created_at,
                       ROW_NUMBER() OVER (ORDER BY created_at) AS rn,
                       COUNT(*) OVER () AS total
                FROM messages
                WHERE guild_id=$1 AND author_name ILIKE $2
            )
            SELECT message_id, author_name, content, is_bot, created_at
            FROM ranked
            WHERE rn % GREATEST(total / $3, 1) = 0
            ORDER BY created_at
            LIMIT $3
            """,
            guild_id, author_like, even,
        )

        merged: dict[int, dict] = {}
        for r in (*recent_rows, *even_rows):
            merged[r["message_id"]] = r
        rows = sorted(merged.values(), key=lambda r: r["created_at"])
        return [
            {
                "author": r["author_name"],
                "is_bot": r["is_bot"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]


class ChunkRepository:
    async def latest_chunked_msg_id(self, channel_id: int) -> int | None:
        """증분 청킹 기준 — 이미 청크로 묶인 마지막 message_id."""
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT max(end_msg_id) AS m FROM message_chunks WHERE channel_id=$1",
            channel_id,
        )
        return row["m"]

    async def insert_chunks(self, rows: list[tuple]) -> None:
        """rows: (channel_id, guild_id, start_msg_id, end_msg_id, start_at, end_at,
        authors, content, embedding_literal)"""
        if not rows:
            return
        pool = await get_pool()
        await pool.executemany(
            """
            INSERT INTO message_chunks
                (channel_id, guild_id, start_msg_id, end_msg_id,
                 start_at, end_at, authors, content, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector)
            """,
            rows,
        )

    async def recall_this_day(
        self, guild_id: int, min_participants: int = 3, min_messages: int = 8
    ) -> dict | None:
        """오늘(KST 월-일)에 해당하는 과거 연도의 '활발한' 대화 청크를 랜덤 1개 반환 (서버 전체)."""
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            WITH cand AS (
                SELECT authors, content, start_at,
                       array_length(string_to_array(authors, ', '), 1) AS participants,
                       (length(content) - length(replace(content, chr(10), '')) + 1) AS msgs
                FROM message_chunks
                WHERE guild_id = $1
                  AND EXTRACT(MONTH FROM start_at AT TIME ZONE 'Asia/Seoul')
                      = EXTRACT(MONTH FROM now() AT TIME ZONE 'Asia/Seoul')
                  AND EXTRACT(DAY FROM start_at AT TIME ZONE 'Asia/Seoul')
                      = EXTRACT(DAY FROM now() AT TIME ZONE 'Asia/Seoul')
                  AND EXTRACT(YEAR FROM start_at AT TIME ZONE 'Asia/Seoul')
                      < EXTRACT(YEAR FROM now() AT TIME ZONE 'Asia/Seoul')
            )
            SELECT authors, content, start_at
            FROM cand
            WHERE participants >= $2 AND msgs >= $3
            ORDER BY random()
            LIMIT 1
            """,
            guild_id, min_participants, min_messages,
        )
        if not row:
            return None
        return {
            "authors": row["authors"],
            "content": row["content"],
            "start_at": row["start_at"],
        }

    async def vector_search(
        self, guild_id: int, embedding_literal: str, limit: int = 5
    ) -> list[dict]:
        """쿼리 임베딩과 cosine 거리가 가까운 대화 청크를 반환 (서버 전체)."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT authors, content, start_at, end_at,
                   embedding <=> $2::vector AS distance
            FROM message_chunks
            WHERE guild_id=$1 AND embedding IS NOT NULL
            ORDER BY embedding <=> $2::vector ASC
            LIMIT $3
            """,
            guild_id, embedding_literal, limit,
        )
        return [
            {
                "authors": r["authors"],
                "content": r["content"],
                "start_at": r["start_at"].isoformat(),
                "end_at": r["end_at"].isoformat(),
                "distance": round(r["distance"], 4),
            }
            for r in rows
        ]


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
