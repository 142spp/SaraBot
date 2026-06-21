"""기존 messages를 청크로 묶어 임베딩하는 일회성 백필 스크립트.

Discord를 거치지 않고 DB에 이미 저장된 메시지만으로 message_chunks를 생성한다.
실행: .venv/bin/python3 src/build_chunks.py
"""
import asyncio

from utils.logger import setup_logging

setup_logging()

from services.embedding_service import EmbeddingService
from services.message_archive_service import MessageArchiveService
from storage.db import close_pool, get_pool, init_schema
from utils.logger import get_logger

logger = get_logger(__name__)


async def main() -> None:
    await init_schema()
    pool = await get_pool()

    channels = await pool.fetch(
        "SELECT DISTINCT channel_id, guild_id FROM messages"
    )
    logger.info(f"Backfill chunks for {len(channels)} channel(s)")

    # _build_chunks는 self._client를 쓰지 않으므로 client=None으로 충분
    archive = MessageArchiveService(None, EmbeddingService())  # type: ignore[arg-type]

    try:
        for row in channels:
            channel_id = row["channel_id"]
            guild_id = row["guild_id"]
            logger.info(f"--- channel={channel_id} 청킹 시작 ---")
            n = await archive._build_chunks(channel_id, guild_id)
            logger.info(f"--- channel={channel_id} 완료: 청크 {n}개 ---")
    finally:
        await close_pool()

    logger.info("Backfill done.")


if __name__ == "__main__":
    asyncio.run(main())
