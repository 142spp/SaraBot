import discord

from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_SUMMARY_LIMIT = 100


class SummarizeRecentChatTool(BaseTool):
    def __init__(self, client: discord.Client) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "summarize_recent_chat"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "summarize_recent_chat",
                "description": "현재 채널의 최근 대화 내용을 가져온다. 가져온 내용을 바탕으로 직접 요약해서 답변한다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "default": 30,
                            "description": "가져올 메시지 수 (최대 100)",
                        }
                    },
                    "required": [],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        limit = min(int(args.get("limit", 30)), MAX_SUMMARY_LIMIT)
        channel = self._client.get_channel(request.channel_id)

        if not channel or not hasattr(channel, "history"):
            return {"ok": False, "error": "CHANNEL_NOT_ACCESSIBLE"}

        messages: list[dict] = []
        async for msg in channel.history(limit=limit):
            if msg.author.bot:
                continue
            messages.append({
                "author": msg.author.display_name,
                "content": msg.content,
            })

        messages.reverse()

        if not messages:
            return {"ok": False, "error": "NO_MESSAGES_FOUND"}

        logger.debug(f"summarize_recent_chat: fetched {len(messages)} messages")
        return {"ok": True, "messages": messages, "count": len(messages)}
