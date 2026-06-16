from services.voice_service import VoiceService
from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)


class GetUserVoiceChannelTool(BaseTool):
    def __init__(self, voice_service: VoiceService) -> None:
        self._voice = voice_service

    @property
    def name(self) -> str:
        return "get_user_voice_channel"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "get_user_voice_channel",
                "description": "요청한 사용자가 현재 접속해 있는 보이스 채널 정보를 가져온다.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        channel = self._voice.get_user_voice_channel(
            request.guild_id, request.user_id
        )
        if not channel:
            return {"ok": False, "error": "USER_NOT_IN_VOICE_CHANNEL"}
        return {
            "ok": True,
            "channel_id": str(channel.id),
            "channel_name": channel.name,
        }


class JoinVoiceTool(BaseTool):
    def __init__(self, voice_service: VoiceService) -> None:
        self._voice = voice_service

    @property
    def name(self) -> str:
        return "join_voice"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "join_voice",
                "description": "사용자가 현재 접속해 있는 보이스 채널에 봇이 입장한다.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        channel = self._voice.get_user_voice_channel(
            request.guild_id, request.user_id
        )
        if not channel:
            return {"ok": False, "error": "USER_NOT_IN_VOICE_CHANNEL"}

        try:
            await self._voice.join(request.guild_id, channel)
            return {"ok": True, "channel_name": channel.name}
        except Exception as e:
            logger.error(f"join_voice failed: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}


class LeaveVoiceTool(BaseTool):
    def __init__(self, voice_service: VoiceService) -> None:
        self._voice = voice_service

    @property
    def name(self) -> str:
        return "leave_voice"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "leave_voice",
                "description": "봇이 현재 접속 중인 보이스 채널에서 퇴장한다.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        left = await self._voice.leave(request.guild_id)
        if not left:
            return {"ok": False, "error": "BOT_NOT_IN_VOICE_CHANNEL"}
        return {"ok": True}
