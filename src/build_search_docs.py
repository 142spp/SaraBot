"""Build experimental search documents over existing message_chunks.

The raw message_chunks table remains the source of truth. This script creates a
separate search layer where several raw chunks are summarized into one
retrieval-oriented document.

Usage:
    PYTHONPATH=src .venv/bin/python src/build_search_docs.py --reset --limit-docs 200
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from utils.logger import setup_logging

setup_logging()

from services.embedding_service import EmbeddingService
from services.llm_service import LLMService
from storage.db import close_pool, get_pool, init_schema
from storage.repositories import SearchDocRepository
from utils.logger import get_logger

logger = get_logger(__name__)

SOFT_GAP = timedelta(minutes=30)
HARD_GAP = timedelta(hours=2)
MIN_SOURCE_CHARS = 500
TARGET_SOURCE_CHARS = 1600
MAX_SOURCE_CHARS = 3000
MAX_SOURCE_CHUNKS = 20
OVERLAP_CHUNKS = 1
INSERT_BATCH_SIZE = 64
DEFAULT_CONCURRENCY = 8


def _source_text(chunks: list) -> str:
    return "\n---\n".join((chunk["content"] or "").strip() for chunk in chunks)


def _authors(chunks: list) -> str:
    names: list[str] = []
    for chunk in chunks:
        for name in (chunk["authors"] or "").split(", "):
            if name and name not in names:
                names.append(name)
    return ", ".join(names)


def build_groups(chunks: list) -> list[list]:
    groups: list[list] = []
    current: list = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        groups.append(current)
        current = current[-OVERLAP_CHUNKS:] if OVERLAP_CHUNKS else []

    for chunk in chunks:
        if not (chunk["content"] or "").strip():
            continue
        if not current:
            current = [chunk]
            continue

        gap = chunk["start_at"] - current[-1]["end_at"]
        current_chars = len(_source_text(current))
        should_split = (
            gap >= HARD_GAP
            or len(current) >= MAX_SOURCE_CHUNKS
            or current_chars >= MAX_SOURCE_CHARS
            or (gap >= SOFT_GAP and current_chars >= MIN_SOURCE_CHARS)
            or (
                current_chars >= TARGET_SOURCE_CHARS
                and gap >= timedelta(minutes=5)
            )
        )
        if should_split:
            flush()
            if gap >= HARD_GAP:
                current = []
        current.append(chunk)

    if current:
        groups.append(current)
    return [group for group in groups if _source_text(group).strip()]


async def summarize_group(llm: LLMService, source: str) -> str:
    prompt = (
        "아래는 디스코드 대화 원문이야. 검색 인덱스에 넣을 요약 문서를 한국어로 작성해.\n"
        "목표는 사용자가 나중에 돌려 말해도 이 대화가 잘 검색되게 하는 거야.\n"
        "추측하지 말고 원문에 있는 내용만 써. 300~500자 정도, 최대 800자.\n"
        "형식:\n"
        "주제: ...\n"
        "인물: ...\n"
        "핵심 내용: ...\n"
        "키워드: ...\n\n"
        f"원문:\n{source[:MAX_SOURCE_CHARS]}"
    )
    return (await llm.judge(prompt)).strip()[:800]


async def summarize_groups(
    llm: LLMService,
    sources: list[str],
    concurrency: int,
) -> list[str]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(source: str) -> str:
        async with semaphore:
            return await summarize_group(llm, source)

    return await asyncio.gather(*(run(source) for source in sources))


async def build_channel(
    pool,
    repo: SearchDocRepository,
    llm: LLMService,
    embedder: EmbeddingService,
    channel_id: int,
    guild_id: int,
    remaining: int | None,
    concurrency: int,
) -> int:
    chunks = await pool.fetch(
        """
        SELECT id, channel_id, guild_id, start_msg_id, end_msg_id,
               start_at, end_at, authors, content
        FROM message_chunks
        WHERE channel_id=$1
        ORDER BY start_msg_id ASC
        """,
        channel_id,
    )
    groups = build_groups(chunks)
    existing = await pool.fetch(
        """
        SELECT start_chunk_id, end_chunk_id
        FROM message_chunk_search_docs
        WHERE channel_id=$1
        """,
        channel_id,
    )
    existing_ranges = {
        (row["start_chunk_id"], row["end_chunk_id"]) for row in existing
    }
    groups = [
        group
        for group in groups
        if (group[0]["id"], group[-1]["id"]) not in existing_ranges
    ]
    if remaining is not None:
        groups = groups[:remaining]
    logger.info(
        f"search doc groups | channel={channel_id} chunks={len(chunks)} groups={len(groups)}"
    )

    total = 0
    for i in range(0, len(groups), INSERT_BATCH_SIZE):
        batch = groups[i : i + INSERT_BATCH_SIZE]
        sources = [_source_text(group)[:MAX_SOURCE_CHARS] for group in batch]
        search_texts = await summarize_groups(llm, sources, concurrency)
        embeddings = await embedder.embed(search_texts)
        rows = [
            (
                guild_id,
                channel_id,
                group[0]["id"],
                group[-1]["id"],
                group[0]["start_msg_id"],
                group[-1]["end_msg_id"],
                group[0]["start_at"],
                group[-1]["end_at"],
                _authors(group),
                source,
                search_text,
                EmbeddingService.to_pgvector(embedding),
            )
            for group, source, search_text, embedding in zip(
                batch,
                sources,
                search_texts,
                embeddings,
            )
        ]
        await repo.insert_docs(rows)
        total += len(rows)
        logger.info(f"search docs inserted | channel={channel_id} total={total}")
    return total


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument(
        "--limit-docs",
        type=int,
        default=0,
        help="Build at most this many search docs across all channels. 0 means all.",
    )
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = parser.parse_args()

    await init_schema()
    pool = await get_pool()
    repo = SearchDocRepository()
    llm = LLMService()
    embedder = EmbeddingService()

    try:
        if args.reset:
            await pool.execute("TRUNCATE message_chunk_search_docs RESTART IDENTITY")
            logger.info("message_chunk_search_docs truncated")

        channels = await pool.fetch(
            """
            SELECT channel_id, guild_id, count(*) AS chunks
            FROM message_chunks
            GROUP BY channel_id, guild_id
            ORDER BY chunks DESC
            """
        )
        total = 0
        limit = args.limit_docs or None
        for row in channels:
            remaining = None if limit is None else max(limit - total, 0)
            if remaining == 0:
                break
            count = await build_channel(
                pool,
                repo,
                llm,
                embedder,
                row["channel_id"],
                row["guild_id"],
                remaining,
                max(1, args.concurrency),
            )
            total += count
        logger.info(f"search doc backfill done | docs={total}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
