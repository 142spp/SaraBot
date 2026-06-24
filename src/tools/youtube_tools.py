from services.youtube_service import YouTubeService, extract_video_id
from tools.base import BaseTool


class SummarizeYoutubeTool(BaseTool):
    def __init__(self, youtube_service: YouTubeService) -> None:
        self._svc = youtube_service

    @property
    def name(self) -> str:
        return "summarize_youtube"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "summarize_youtube",
                "description": (
                    "유튜브 영상 링크의 내용을 자막 기반으로 요약한다. "
                    "사용자가 유튜브 링크를 주면서 '이거 뭐야/요약해줘/무슨 내용이야' "
                    "같이 물을 때 사용. 자막이 없는 영상은 못 본다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "유튜브 영상 URL (youtube.com/watch, youtu.be, shorts 등).",
                        },
                    },
                    "required": ["url"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        url = (args.get("url") or "").strip()
        if not url or not extract_video_id(url):
            return {"ok": False, "error": "유효한 유튜브 링크가 필요해."}
        return await self._svc.summarize(url)
