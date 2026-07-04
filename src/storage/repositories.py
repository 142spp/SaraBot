from datetime import timedelta, timezone

from storage.db import get_pool
from utils.logger import get_logger

logger = get_logger(__name__)
KST = timezone(timedelta(hours=9))


def _discord_message_url(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _kst_iso(dt) -> str:
    return dt.astimezone(KST).isoformat()


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
        before_message_id: int | None = None,
        exclude_mention_user_id: int | None = None,
        date_from=None,
        date_to=None,
    ) -> list[dict]:
        """content에 terms 일부(OR)를 포함하는 메시지를 점수순으로 반환 (서버 전체).

        author가 주어지면 작성자 이름(부분일치)으로도 필터링한다.
        """
        pool = await get_pool()
        conditions = ["guild_id = $1", "is_bot = FALSE"]
        params: list = [guild_id]
        if author:
            params.append(f"%{author}%")
            conditions.append(f"author_name ILIKE ${len(params)}")
        if before_message_id:
            params.append(before_message_id)
            conditions.append(f"message_id < ${len(params)}")
        if exclude_mention_user_id:
            params.append(f"%<@{exclude_mention_user_id}>%")
            conditions.append(f"content NOT ILIKE ${len(params)}")
            params.append(f"%<@!{exclude_mention_user_id}>%")
            conditions.append(f"content NOT ILIKE ${len(params)}")
        if date_from:
            params.append(date_from)
            conditions.append(f"created_at >= ${len(params)}")
        if date_to:
            params.append(date_to)
            conditions.append(f"created_at < ${len(params)}")
        term_conditions: list[str] = []
        score_parts: list[str] = []
        for idx, term in enumerate(terms):
            params.append(f"%{term}%")
            term_conditions.append(f"content ILIKE ${len(params)}")
            weight = 4 if idx == 0 else 1
            score_parts.append(
                f"CASE WHEN content ILIKE ${len(params)} THEN {weight} ELSE 0 END"
            )
        if term_conditions:
            conditions.append(f"({' OR '.join(term_conditions)})")
        params.append(limit)
        score_sql = " + ".join(score_parts) if score_parts else "0"
        sql = (
            "SELECT message_id, channel_id, guild_id, author_name, content, "
            f"is_bot, created_at, ({score_sql}) AS keyword_score "
            "FROM messages "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY keyword_score DESC, created_at DESC LIMIT ${len(params)}"
        )
        rows = await pool.fetch(sql, *params)
        return [
            {
                "message_id": r["message_id"],
                "channel_id": r["channel_id"],
                "guild_id": r["guild_id"],
                "author": r["author_name"],
                "is_bot": r["is_bot"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat(),
                "created_at_kst": _kst_iso(r["created_at"]),
                "keyword_score": r["keyword_score"],
                "source_url": _discord_message_url(
                    r["guild_id"], r["channel_id"], r["message_id"]
                ),
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

    async def keyword_search(
        self,
        guild_id: int,
        terms: list[str],
        limit: int = 20,
        author: str | None = None,
        channel_id: int | None = None,
        before_message_id: int | None = None,
        exclude_mention_user_id: int | None = None,
        date_from=None,
        date_to=None,
    ) -> list[dict]:
        """content에 terms 일부(OR)를 포함하는 대화 청크를 점수순으로 반환."""
        if not terms and not author:
            return []

        pool = await get_pool()
        conditions = ["guild_id = $1"]
        params: list = [guild_id]
        if author:
            params.append(f"%{author}%")
            conditions.append(f"authors ILIKE ${len(params)}")
        if channel_id:
            params.append(channel_id)
            conditions.append(f"channel_id = ${len(params)}")
        if before_message_id:
            params.append(before_message_id)
            conditions.append(f"end_msg_id < ${len(params)}")
        if exclude_mention_user_id:
            params.append(f"%<@{exclude_mention_user_id}>%")
            conditions.append(f"content NOT ILIKE ${len(params)}")
            params.append(f"%<@!{exclude_mention_user_id}>%")
            conditions.append(f"content NOT ILIKE ${len(params)}")
        if date_from:
            params.append(date_from)
            conditions.append(f"start_at >= ${len(params)}")
        if date_to:
            params.append(date_to)
            conditions.append(f"start_at < ${len(params)}")

        term_conditions: list[str] = []
        score_parts: list[str] = []
        for idx, term in enumerate(terms):
            params.append(f"%{term}%")
            term_conditions.append(f"content ILIKE ${len(params)}")
            weight = 4 if idx == 0 else 1
            score_parts.append(
                f"CASE WHEN content ILIKE ${len(params)} THEN {weight} ELSE 0 END"
            )
        if term_conditions:
            conditions.append(f"({' OR '.join(term_conditions)})")

        params.append(limit)
        score_sql = " + ".join(score_parts) if score_parts else "0"
        rows = await pool.fetch(
            f"""
            SELECT id, channel_id, start_msg_id, end_msg_id,
                   authors, content, start_at, end_at,
                   ({score_sql}) AS keyword_score
            FROM message_chunks
            WHERE {" AND ".join(conditions)}
            ORDER BY keyword_score DESC, end_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
        return [
            {
                "id": r["id"],
                "channel_id": r["channel_id"],
                "guild_id": guild_id,
                "start_msg_id": r["start_msg_id"],
                "end_msg_id": r["end_msg_id"],
                "authors": r["authors"],
                "content": r["content"],
                "start_at": r["start_at"].isoformat(),
                "end_at": r["end_at"].isoformat(),
                "start_at_kst": _kst_iso(r["start_at"]),
                "end_at_kst": _kst_iso(r["end_at"]),
                "keyword_score": r["keyword_score"],
                "source_url": _discord_message_url(
                    guild_id, r["channel_id"], r["start_msg_id"]
                ),
                "end_source_url": _discord_message_url(
                    guild_id, r["channel_id"], r["end_msg_id"]
                ),
            }
            for r in rows
        ]

    async def recall_this_day(
        self,
        guild_id: int,
        min_participants: int = 2,
        min_messages: int = 5,
        limit: int = 8,
    ) -> list[dict]:
        """오늘(KST 월-일)의 과거 대화 후보를 웃음(ㅋ/ㅎ) 밀도 순으로 반환 (서버 전체).
        최소 활성(참여자·메시지) 바닥선을 깐 뒤 웃음 점수 상위 N개를 뽑는다.
        ㅋ는 거의 웃음이라 가중치 2, ㅎ는 노이즈가 있어 가중치 1."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            WITH cand AS (
                SELECT authors, content, start_at,
                       array_length(string_to_array(authors, ', '), 1) AS participants,
                       (length(content) - length(replace(content, chr(10), '')) + 1) AS msgs,
                       (length(content) - length(replace(content, 'ㅋ', ''))) AS laughs_k,
                       (length(content) - length(replace(content, 'ㅎ', ''))) AS laughs_h
                FROM message_chunks
                WHERE guild_id = $1
                  AND EXTRACT(MONTH FROM start_at AT TIME ZONE 'Asia/Seoul')
                      = EXTRACT(MONTH FROM now() AT TIME ZONE 'Asia/Seoul')
                  AND EXTRACT(DAY FROM start_at AT TIME ZONE 'Asia/Seoul')
                      = EXTRACT(DAY FROM now() AT TIME ZONE 'Asia/Seoul')
                  AND EXTRACT(YEAR FROM start_at AT TIME ZONE 'Asia/Seoul')
                      < EXTRACT(YEAR FROM now() AT TIME ZONE 'Asia/Seoul')
            )
            SELECT authors, content, start_at, (2 * laughs_k + laughs_h) AS fun_score
            FROM cand
            WHERE participants >= $2 AND msgs >= $3
            ORDER BY fun_score DESC, random()
            LIMIT $4
            """,
            guild_id, min_participants, min_messages, limit,
        )
        return [
            {
                "authors": r["authors"],
                "content": r["content"],
                "start_at": r["start_at"],
                "fun_score": r["fun_score"],
            }
            for r in rows
        ]

    async def vector_search(
        self,
        guild_id: int,
        embedding_literal: str,
        limit: int = 5,
        author: str | None = None,
        channel_id: int | None = None,
        before_message_id: int | None = None,
        exclude_mention_user_id: int | None = None,
        date_from=None,
        date_to=None,
    ) -> list[dict]:
        """쿼리 임베딩과 cosine 거리가 가까운 대화 청크를 반환 (서버 전체)."""
        pool = await get_pool()
        conditions = ["guild_id=$1", "embedding IS NOT NULL"]
        params: list = [guild_id, embedding_literal]
        if author:
            params.append(f"%{author}%")
            conditions.append(f"authors ILIKE ${len(params)}")
        if channel_id:
            params.append(channel_id)
            conditions.append(f"channel_id = ${len(params)}")
        if before_message_id:
            params.append(before_message_id)
            conditions.append(f"end_msg_id < ${len(params)}")
        if exclude_mention_user_id:
            params.append(f"%<@{exclude_mention_user_id}>%")
            conditions.append(f"content NOT ILIKE ${len(params)}")
            params.append(f"%<@!{exclude_mention_user_id}>%")
            conditions.append(f"content NOT ILIKE ${len(params)}")
        if date_from:
            params.append(date_from)
            conditions.append(f"start_at >= ${len(params)}")
        if date_to:
            params.append(date_to)
            conditions.append(f"start_at < ${len(params)}")
        params.append(limit)
        rows = await pool.fetch(
            f"""
            SELECT id, channel_id, start_msg_id, end_msg_id,
                   authors, content, start_at, end_at,
                   embedding <=> $2::vector AS distance
            FROM message_chunks
            WHERE {" AND ".join(conditions)}
            ORDER BY embedding <=> $2::vector ASC
            LIMIT ${len(params)}
            """,
            *params,
        )
        return [
            {
                "id": r["id"],
                "channel_id": r["channel_id"],
                "guild_id": guild_id,
                "start_msg_id": r["start_msg_id"],
                "end_msg_id": r["end_msg_id"],
                "authors": r["authors"],
                "content": r["content"],
                "start_at": r["start_at"].isoformat(),
                "end_at": r["end_at"].isoformat(),
                "start_at_kst": _kst_iso(r["start_at"]),
                "end_at_kst": _kst_iso(r["end_at"]),
                "distance": round(r["distance"], 4),
                "source_url": _discord_message_url(
                    guild_id, r["channel_id"], r["start_msg_id"]
                ),
                "end_source_url": _discord_message_url(
                    guild_id, r["channel_id"], r["end_msg_id"]
                ),
            }
            for r in rows
        ]

    async def expand_context(
        self,
        guild_id: int,
        matches: list[dict],
        before: int = 1,
        after: int = 1,
        max_chars: int = 1800,
    ) -> list[dict]:
        """최종 검색 결과마다 같은 채널의 앞뒤 청크를 붙여 답변 문맥을 보강한다."""
        if not matches:
            return []

        pool = await get_pool()
        expanded: list[dict] = []
        async with pool.acquire() as conn:
            for match in matches:
                before_rows = await conn.fetch(
                    """
                    SELECT id, channel_id, start_msg_id, end_msg_id,
                           authors, content, start_at, end_at
                    FROM message_chunks
                    WHERE guild_id=$1 AND channel_id=$2 AND end_msg_id < $3
                    ORDER BY end_msg_id DESC
                    LIMIT $4
                    """,
                    guild_id,
                    match["channel_id"],
                    match["start_msg_id"],
                    before,
                )
                after_rows = await conn.fetch(
                    """
                    SELECT id, channel_id, start_msg_id, end_msg_id,
                           authors, content, start_at, end_at
                    FROM message_chunks
                    WHERE guild_id=$1 AND channel_id=$2 AND start_msg_id > $3
                    ORDER BY start_msg_id ASC
                    LIMIT $4
                    """,
                    guild_id,
                    match["channel_id"],
                    match["end_msg_id"],
                    after,
                )
                chunks = list(reversed(before_rows)) + [match] + list(after_rows)
                context_parts: list[str] = []
                context_ids: list[int] = []
                context_sources: list[dict] = []
                for chunk in chunks:
                    context_ids.append(chunk["id"])
                    context_sources.append(
                        {
                            "chunk_id": chunk["id"],
                            "start_at": chunk["start_at"].isoformat()
                            if hasattr(chunk["start_at"], "isoformat")
                            else chunk["start_at"],
                            "end_at": chunk["end_at"].isoformat()
                            if hasattr(chunk["end_at"], "isoformat")
                            else chunk["end_at"],
                            "source_url": _discord_message_url(
                                guild_id,
                                chunk["channel_id"],
                                chunk["start_msg_id"],
                            ),
                        }
                    )
                    text = (chunk["content"] or "").strip()
                    if text:
                        context_parts.append(text)
                context = "\n---\n".join(context_parts)
                item = {
                    **match,
                    "context_chunk_ids": context_ids,
                    "context_sources": context_sources,
                    "context_content": context[:max_chars],
                }
                expanded.append(item)
        return expanded


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


DEFAULT_AFFINITY = 50
MIN_AFFINITY = 0
MAX_AFFINITY = 100


class AffinityRepository:
    async def get(self, guild_id: int, user_id: int) -> int:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT score FROM user_affinity WHERE guild_id=$1 AND user_id=$2",
            guild_id, user_id,
        )
        return row["score"] if row else DEFAULT_AFFINITY

    async def adjust(self, guild_id: int, user_id: int, delta: int) -> int:
        """delta만큼 호감도를 올리고(내리고) 0~100으로 clamp한 새 값을 반환."""
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO user_affinity (guild_id, user_id, score, updated_at)
            VALUES ($1, $2, LEAST($4::int, GREATEST($3::int, $5::int + $6::int)), NOW())
            ON CONFLICT (guild_id, user_id) DO UPDATE
                SET score = LEAST($4::int, GREATEST($3::int, user_affinity.score + $6::int)),
                    updated_at = NOW()
            RETURNING score
            """,
            guild_id, user_id, MIN_AFFINITY, MAX_AFFINITY, DEFAULT_AFFINITY, delta,
        )
        return row["score"]
