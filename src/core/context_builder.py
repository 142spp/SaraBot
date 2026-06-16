import discord

from discord_adapter.message_parser import BotRequest
from services.music_service import MusicService


class ContextBuilder:
    def __init__(self, client: discord.Client, music_service: MusicService | None = None) -> None:
        self._client = client
        self._music = music_service

    async def build(self, request: BotRequest) -> dict:
        guild = self._client.get_guild(request.guild_id)
        bot_member = guild.get_member(self._client.user.id) if guild else None

        guild_ctx = {
            "id": str(request.guild_id),
            "name": guild.name if guild else "Unknown",
            "persona": "귀엽고 친근한 여자애처럼 행동해. 반말로 대화해도 돼.",
        }

        user_ctx: dict = {
            "id": str(request.user_id),
            "display_name": request.display_name,
            "is_admin": request.is_admin,
            "voice_channel": None,
        }
        if request.user_voice_channel_id and guild:
            vc = guild.get_channel(request.user_voice_channel_id)
            user_ctx["voice_channel"] = {
                "id": str(request.user_voice_channel_id),
                "name": vc.name if vc else "Unknown",
            }

        bot_voice: dict | None = None
        if bot_member and bot_member.voice and bot_member.voice.channel:
            bot_voice = {
                "id": str(bot_member.voice.channel.id),
                "name": bot_member.voice.channel.name,
            }

        recent_messages: list[dict] = []
        channel = self._client.get_channel(request.channel_id)
        if channel and hasattr(channel, "history"):
            async for msg in channel.history(
                limit=20, before=discord.Object(id=request.message_id)
            ):
                if msg.author.bot:
                    continue
                recent_messages.append(
                    {"author": msg.author.display_name, "content": msg.content}
                )
            recent_messages.reverse()

        music_state: dict = {"current_track": None, "queue_length": 0, "is_playing": False}
        if self._music:
            info = self._music.get_queue_info(request.guild_id)
            music_state = {
                "is_playing": info["is_playing"],
                "current_track": info["current_track"],
                "queue_length": info["queue_length"],
            }

        return {
            "guild": guild_ctx,
            "user": user_ctx,
            "bot_state": {
                "in_voice_channel": bot_voice is not None,
                "voice_channel": bot_voice,
            },
            "music_state": music_state,
            "recent_messages": recent_messages,
        }
