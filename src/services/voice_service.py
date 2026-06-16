import asyncio

import discord

from utils.logger import get_logger

logger = get_logger(__name__)


class VoiceService:
    def __init__(self, client: discord.Client) -> None:
        self._client = client

    def get_user_voice_channel(
        self, guild_id: int, user_id: int
    ) -> discord.VoiceChannel | None:
        guild = self._client.get_guild(guild_id)
        if not guild:
            return None
        member = guild.get_member(user_id)
        if not member or not member.voice or not member.voice.channel:
            return None
        return member.voice.channel

    def get_bot_voice_client(self, guild_id: int) -> discord.VoiceClient | None:
        guild = self._client.get_guild(guild_id)
        if not guild:
            return None
        return guild.voice_client  # type: ignore[return-value]

    async def join(
        self, guild_id: int, channel: discord.VoiceChannel
    ) -> discord.VoiceClient:
        existing = self.get_bot_voice_client(guild_id)
        if existing:
            if existing.channel.id == channel.id:
                logger.debug(f"Already in channel {channel.name}, skipping join")
                return existing
            await existing.move_to(channel)
            logger.info(f"Moved to voice channel: {channel.name}")
            return existing

        vc = await channel.connect()
        logger.info(f"Joined voice channel: {channel.name} (guild={guild_id})")
        return vc

    async def leave(self, guild_id: int) -> bool:
        vc = self.get_bot_voice_client(guild_id)
        if not vc:
            return False
        await vc.disconnect()
        logger.info(f"Left voice channel (guild={guild_id})")
        return True
