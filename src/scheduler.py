import datetime

import discord
from discord.ext import tasks

from services.message_archive_service import MessageArchiveService
from utils.logger import get_logger

logger = get_logger(__name__)

KST = datetime.timezone(datetime.timedelta(hours=9))


def setup_daily_recall(
    client: discord.Client,
    archive_service: MessageArchiveService,
    channel_id: int,
    hour: int = 21,
) -> None:
    """매일 hour시(KST)에 'N년 전 오늘'을 channel_id에 자동 포스팅한다."""
    run_time = datetime.time(hour=hour, minute=0, tzinfo=KST)
    last_posted: dict[str, datetime.date | None] = {"date": None}

    @tasks.loop(time=run_time)
    async def daily_recall() -> None:
        today = datetime.datetime.now(KST).date()
        if last_posted["date"] == today:  # 재시작 등으로 인한 중복 방지
            return
        channel = client.get_channel(channel_id)
        if channel is None:
            logger.warning(f"daily_recall: channel {channel_id} not found")
            return
        try:
            res = await archive_service.recall_this_day(channel.guild.id, channel_id)
            last_posted["date"] = today
            logger.info(f"daily_recall ran | found={res.get('found')}")
        except Exception as e:
            logger.error(f"daily_recall error: {e}", exc_info=True)

    @daily_recall.before_loop
    async def _before() -> None:
        await client.wait_until_ready()

    daily_recall.start()
    logger.info(
        f"daily_recall scheduled | {hour:02d}:00 KST → channel {channel_id}"
    )
