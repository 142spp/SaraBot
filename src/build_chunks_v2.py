"""Build experimental v2 RAG chunks into message_chunks_v2.

The existing message_chunks table is left untouched. This script rebuilds only
the shadow table so retrieval quality can be compared before any swap.

Usage:
    PYTHONPATH=src .venv/bin/python src/build_chunks_v2.py --reset
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from utils.logger import setup_logging

setup_logging()

from services.embedding_service import EmbeddingService
from storage.db import close_pool, get_pool, init_schema
from utils.logger import get_logger

logger = get_logger(__name__)

SOFT_GAP = timedelta(minutes=15)
HARD_GAP = timedelta(hours=2)
CHUNK_MIN_CHARS = 250
CHUNK_TARGET_CHARS = 500
CHUNK_MAX_CHARS = 800
CHUNK_MAX_MESSAGES = 40
CHUNK_OVERLAP_MESSAGES = 2
MAX_MSG_CHARS = 600
INSERT_BATCH_SIZE = 200


def _message_line(row) -> str:
    content = (row["content"] or "").strip()
    return f'{row["author_name"]}: {content[:MAX_MSG_CHARS]}'


def _chunk_text(rows: list) -> str:
    return "\n".join(_message_line(row) for row in rows if (row["content"] or "").strip())


def _authors(rows: list) -> str:
    names: list[str] = []
    for row in rows:
        name = row["author_name"]
        if name not in names:
            names.append(name)
    return ", ".join(names)


def _trim_to_max(rows: list) -> list:
    while len(rows) > 1 and len(_chunk_text(rows)) > CHUNK_MAX_CHARS:
        rows = rows[:-1]
    return rows


def build_groups(messages: list) -> list[list]:
    groups: list[list] = []
    current: list = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        groups.append(_trim_to_max(current))
        current = current[-CHUNK_OVERLAP_MESSAGES:] if CHUNK_OVERLAP_MESSAGES else []

    for msg in messages:
        if not (msg["content"] or "").strip():
            continue

        if not current:
            current = [msg]
            continue

        gap = msg["created_at"] - current[-1]["created_at"]
        current_chars = len(_chunk_text(current))

        if gap >= HARD_GAP:
            flush()
            current = [msg]
            continue

        should_split = (
            len(current) >= CHUNK_MAX_MESSAGES
            or current_chars >= CHUNK_MAX_CHARS
            or (gap >= SOFT_GAP and current_chars >= CHUNK_MIN_CHARS)
            or (
                current_chars >= CHUNK_TARGET_CHARS
                and gap >= timedelta(minutes=3)
            )
        )
        if should_split:
            flush()

        current.append(msg)

    if current:
        groups.append(_trim_to_max(current))
    return [group for group in groups if _chunk_text(group).strip()]


async def _insert_chunks(pool, rows: list[tuple]) -> None:
    if not rows:
        return
    await pool.executemany(
        """
        INSERT INTO message_chunks_v2
            (channel_id, guild_id, start_msg_id, end_msg_id,
             start_at, end_at, authors, content, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector)
        """,
        rows,
    )


async def build_channel(pool, embedder: EmbeddingService, channel_id: int, guild_id: int) -> int:
    messages = await pool.fetch(
        """
        SELECT message_id, author_name, content, created_at
        FROM messages
        WHERE channel_id=$1
          AND content IS NOT NULL
          AND btrim(content) <> ''
        ORDER BY message_id ASC
        """,
        channel_id,
    )
    groups = build_groups(messages)
    logger.info(
        f"v2 chunk groups | channel={channel_id} messages={len(messages)} groups={len(groups)}"
    )

    total = 0
    for i in range(0, len(groups), INSERT_BATCH_SIZE):
        batch = groups[i : i + INSERT_BATCH_SIZE]
        texts = [_chunk_text(group)[:CHUNK_MAX_CHARS] for group in batch]
        embeddings = await embedder.embed(texts)
        rows = [
            (
                channel_id,
                guild_id,
                group[0]["message_id"],
                group[-1]["message_id"],
                group[0]["created_at"],
                group[-1]["created_at"],
                _authors(group),
                text,
                EmbeddingService.to_pgvector(embedding),
            )
            for group, text, embedding in zip(batch, texts, embeddings)
        ]
        await _insert_chunks(pool, rows)
        total += len(rows)
        logger.info(f"v2 chunks inserted | channel={channel_id} total={total}")
    return total


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="TRUNCATE message_chunks_v2 before building it.",
    )
    args = parser.parse_args()

    await init_schema()
    pool = await get_pool()
    embedder = EmbeddingService()

    try:
        if args.reset:
            await pool.execute("TRUNCATE message_chunks_v2 RESTART IDENTITY")
            logger.info("message_chunks_v2 truncated")

        channels = await pool.fetch(
            "SELECT DISTINCT channel_id, guild_id FROM messages ORDER BY channel_id"
        )
        total = 0
        for row in channels:
            count = await build_channel(
                pool,
                embedder,
                row["channel_id"],
                row["guild_id"],
            )
            total += count
        logger.info(f"v2 backfill done | chunks={total}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
