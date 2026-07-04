"""Backfill local BGE-M3 embeddings for message_chunks.

Usage:
    PYTHONPATH=src .venv/bin/python src/backfill_bge_m3_embeddings.py --limit 1000
"""

from __future__ import annotations

import argparse
import asyncio
import time

from utils.logger import setup_logging

setup_logging()

from services.local_embedding_service import LocalEmbeddingService
from storage.db import close_pool, get_pool, init_schema
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 64


async def fetch_batch(pool, limit: int):
    return await pool.fetch(
        """
        SELECT id, content
        FROM message_chunks
        WHERE embedding_bge_m3 IS NULL
          AND content IS NOT NULL
          AND btrim(content) <> ''
        ORDER BY id
        LIMIT $1
        """,
        limit,
    )


async def update_batch(pool, rows: list, vectors: list[list[float]]) -> None:
    values = [
        (
            row["id"],
            LocalEmbeddingService.to_pgvector(vector),
        )
        for row, vector in zip(rows, vectors)
    ]
    await pool.executemany(
        """
        UPDATE message_chunks
        SET embedding_bge_m3 = $2::vector
        WHERE id = $1
        """,
        values,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 means all remaining rows")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()

    await init_schema()
    pool = await get_pool()
    embedder = LocalEmbeddingService(batch_size=args.batch_size)
    total = 0
    started = time.monotonic()

    try:
        while True:
            remaining_limit = args.limit - total if args.limit else args.batch_size
            if args.limit and remaining_limit <= 0:
                break
            batch_limit = min(args.batch_size, remaining_limit) if args.limit else args.batch_size
            rows = await fetch_batch(pool, batch_limit)
            if not rows:
                break

            texts = [row["content"] for row in rows]
            vectors = await embedder.embed_documents(texts)
            await update_batch(pool, rows, vectors)
            total += len(rows)

            elapsed = max(time.monotonic() - started, 0.001)
            logger.info(
                f"BGE-M3 backfill progress | total={total} "
                f"rate={total / elapsed:.1f} chunks/sec"
            )
    finally:
        await close_pool()

    elapsed = max(time.monotonic() - started, 0.001)
    logger.info(f"BGE-M3 backfill done | total={total} elapsed={elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
