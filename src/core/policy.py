import discord

from discord_adapter.message_parser import BotRequest
from utils.logger import get_logger

logger = get_logger(__name__)

# 관리자만 사용 가능한 tool
ADMIN_ONLY_TOOLS: set[str] = set()

# 보이스 기능이 필요한 tool
VOICE_TOOLS = {"join_voice", "leave_voice", "play_music", "skip_music", "show_queue"}


class PolicyResult:
    def __init__(self, ok: bool, reason: str = "") -> None:
        self.ok = ok
        self.reason = reason


class PolicyLayer:
    def __init__(self, client: discord.Client | None = None) -> None:
        self._client = client

    async def check(
        self, request: BotRequest, tool_name: str, args: dict
    ) -> PolicyResult:
        if tool_name in ADMIN_ONLY_TOOLS and not request.is_admin:
            return PolicyResult(ok=False, reason="ADMIN_ONLY")

        if tool_name in VOICE_TOOLS and self._client:
            guild = self._client.get_guild(request.guild_id)
            if guild:
                bot_member = guild.get_member(self._client.user.id)
                if bot_member:
                    # join_voice는 Connect/Speak 권한 필요
                    if tool_name == "join_voice" and request.user_voice_channel_id:
                        channel = guild.get_channel(request.user_voice_channel_id)
                        if channel:
                            perms = channel.permissions_for(bot_member)
                            if not perms.connect:
                                return PolicyResult(ok=False, reason="BOT_NO_CONNECT_PERMISSION")
                            if not perms.speak:
                                return PolicyResult(ok=False, reason="BOT_NO_SPEAK_PERMISSION")

        return PolicyResult(ok=True)
