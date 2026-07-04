import discord

from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)


class SayTool(BaseTool):
    """중간 메시지 전송 — 루프는 계속된다."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "say"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "say",
                "description": (
                    "작업 전에 사용자에게 중간 메시지를 즉시 전송한다. "
                    "루프는 종료되지 않으므로 이후 다른 툴을 계속 호출할 수 있다. "
                    "확인 중이거나 처리 시간이 걸릴 때 사용. "
                    "최종 답변은 반드시 respond_text로 마무리한다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                    },
                    "required": ["message"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        message = args.get("message")
        if not message:
            return {"ok": True}  # 빈 say는 조용히 무시
        channel = self._client.get_channel(request.channel_id)
        if channel and hasattr(channel, "send"):
            await channel.send(message)
            logger.info(f"say → #{channel.name}: {message[:80]!r}")
        return {"ok": True}


class RespondTextTool(BaseTool):
    @property
    def name(self) -> str:
        return "respond_text"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "respond_text",
                "description": (
                    "사용자에게 최종 답변을 보낸다. 항상 마지막에 호출한다. "
                    "search_chat_history 결과에 evidence_embeds가 있으면 embeds에 그대로 넣어 "
                    "텍스트와 근거를 한 메시지로 함께 보여준다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "embeds": {
                            "type": "array",
                            "description": (
                                "선택. search_chat_history가 반환한 evidence_embeds를 그대로 넣는다."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "description": {"type": "string"},
                                    "url": {"type": "string"},
                                    "fields": {"type": "array"},
                                    "footer": {"type": "string"},
                                },
                            },
                        },
                        "image_notes": {
                            "type": "string",
                            "description": (
                                "이미지가 첨부된 대화일 때만 채운다. 이미지에 보이는 것을 "
                                "객관적으로 빠짐없이 기록한다(텍스트·숫자·사물·인물·맥락). "
                                "사용자에게는 보이지 않고, 나중에 그 이미지에 대한 후속 질문에 "
                                "참고하려고 저장된다. 이미지가 없으면 비워둔다."
                            ),
                        },
                    },
                    "required": ["message"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        message = args.get("message")
        if not message:
            # message 누락 시 크래시 대신 루프 계속 → LLM이 다시 제대로 호출
            return {"ok": False, "error": "message 인자가 비어있어. message를 채워서 다시 호출해."}
        result = {"ok": True, "message": message}
        embeds = args.get("embeds")
        if isinstance(embeds, list):
            result["embeds"] = embeds[:10]
        image_notes = (args.get("image_notes") or "").strip()
        if image_notes:
            result["image_notes"] = image_notes
        return result
