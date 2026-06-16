from services.music_service import MusicService
from services.voice_service import VoiceService
from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)


class SearchMusicTool(BaseTool):
    def __init__(self, music_service: MusicService) -> None:
        self._music = music_service

    @property
    def name(self) -> str:
        return "search_music"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "search_music",
                "description": "검색어를 기반으로 재생 가능한 음악 후보를 검색한다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        query = args["query"]
        limit = min(int(args.get("limit", 5)), 10)
        tracks = await self._music.search(query, limit)
        if not tracks:
            return {"ok": False, "error": "SEARCH_NO_RESULTS"}
        return {
            "ok": True,
            "results": [
                {
                    "title": t.title,
                    "duration": t.duration,
                    "webpage_url": t.webpage_url,
                }
                for t in tracks
            ],
        }


class PlayMusicTool(BaseTool):
    def __init__(self, music_service: MusicService, voice_service: VoiceService) -> None:
        self._music = music_service
        self._voice = voice_service

    @property
    def name(self) -> str:
        return "play_music"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "play_music",
                "description": (
                    "검색어로 음악을 큐에 추가하고 재생한다. "
                    "봇이 보이스 채널에 없으면 자동으로 입장한다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색어 또는 URL"},
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        if not request.user_voice_channel_id:
            return {"ok": False, "error": "USER_NOT_IN_VOICE_CHANNEL"}

        # 봇이 보이스 채널에 없으면 자동 입장
        vc = self._voice.get_bot_voice_client(request.guild_id)
        if not vc:
            channel = self._voice.get_user_voice_channel(
                request.guild_id, request.user_id
            )
            if not channel:
                return {"ok": False, "error": "USER_NOT_IN_VOICE_CHANNEL"}
            try:
                await self._voice.join(request.guild_id, channel)
            except Exception as e:
                logger.error(f"Auto join failed: {e}", exc_info=True)
                return {"ok": False, "error": f"VOICE_JOIN_FAILED: {e}"}

        track, is_playing_now = await self._music.enqueue(
            request.guild_id, args["query"], request.channel_id
        )
        if not track:
            return {"ok": False, "error": "TRACK_NOT_FOUND"}

        return {
            "ok": True,
            "title": track.title,
            "duration": track.duration,
            "is_playing_now": is_playing_now,
        }


class SkipMusicTool(BaseTool):
    def __init__(self, music_service: MusicService) -> None:
        self._music = music_service

    @property
    def name(self) -> str:
        return "skip_music"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "skip_music",
                "description": "현재 재생 중인 곡을 스킵하고 다음 곡을 재생한다.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        skipped = await self._music.skip(request.guild_id)
        if not skipped:
            return {"ok": False, "error": "NOTHING_PLAYING"}
        return {"ok": True, "skipped_title": skipped.title}


class ShowQueueTool(BaseTool):
    def __init__(self, music_service: MusicService) -> None:
        self._music = music_service

    @property
    def name(self) -> str:
        return "show_queue"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "show_queue",
                "description": "현재 서버의 음악 재생 큐를 반환한다.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        info = self._music.get_queue_info(request.guild_id)
        return {"ok": True, **info}
