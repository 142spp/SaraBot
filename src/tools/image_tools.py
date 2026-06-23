import io
from datetime import date

import discord

from services.image_service import ImageService
from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)

DAILY_LIMIT = 20  # 유저당 하루 생성 횟수
MAX_INPUT_IMAGES = 4  # 편집 시 입력 이미지 최대 개수


def _image_attachments(attachments) -> list:
    return [
        a
        for a in attachments
        if getattr(a, "content_type", None)
        and a.content_type.startswith("image/")
    ]


class GenerateImageTool(BaseTool):
    def __init__(self, client: discord.Client, image_service: ImageService) -> None:
        self._client = client
        self._image = image_service
        self._usage: dict[int, tuple[date, int]] = {}  # user_id -> (날짜, 횟수)

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "generate_image",
                "description": (
                    "이미지를 생성해서 채널에 바로 올린다. "
                    "사용자가 그림/이미지를 그려달라고 할 때 사용. "
                    "첨부된 이미지가 있으면 그 이미지를 바탕으로 편집/변형하고, "
                    "없으면 프롬프트로 새로 그린다. "
                    "생성에 시간이 걸리니 호출 전에 say로 먼저 알리고, "
                    "생성 후 respond_text로 마무리한다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": (
                                "그릴 내용을 구체적으로 묘사. 소재·스타일·구도·색감·배경을 "
                                "자세히 적을수록 품질이 좋다."
                            ),
                        }
                    },
                    "required": ["prompt"],
                },
            },
        }

    def _over_limit(self, user_id: int) -> bool:
        today = date.today()
        d, c = self._usage.get(user_id, (today, 0))
        if d != today:
            c = 0
        return c >= DAILY_LIMIT

    def _record(self, user_id: int) -> None:
        today = date.today()
        d, c = self._usage.get(user_id, (today, 0))
        if d != today:
            c = 0
        self._usage[user_id] = (today, c + 1)

    async def execute(self, args: dict, request) -> dict:
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt가 비어있어. 뭘 그릴지 채워서 호출해."}

        if self._over_limit(request.user_id):
            return {
                "ok": False,
                "error": f"오늘 그림 생성 한도({DAILY_LIMIT}장)를 다 썼어. 내일 다시 해줘.",
            }

        channel = self._client.get_channel(request.channel_id)
        if not channel or not hasattr(channel, "send"):
            return {"ok": False, "error": "CHANNEL_NOT_ACCESSIBLE"}

        # 첨부 이미지가 있으면 편집(image-to-image), 없으면 새로 생성
        image_atts = _image_attachments(request.attachments)[:MAX_INPUT_IMAGES]
        if image_atts:
            files: list[tuple] = []
            for a in image_atts:
                try:
                    raw = await a.read()
                except Exception as e:
                    logger.warning(f"attachment read failed: {e}")
                    continue
                files.append(
                    (a.filename or "image.png", raw, a.content_type or "image/png")
                )
            if not files:
                return {"ok": False, "error": "첨부 이미지를 읽지 못했어. 다시 올려줘."}
            logger.info(f"generate_image | edit mode, {len(files)} input image(s)")
            data = await self._image.edit(prompt, files)
        else:
            data = await self._image.generate(prompt)

        if not data:
            return {"ok": False, "error": "이미지 생성에 실패했어. 잠깐 뒤에 다시 해줘."}

        self._record(request.user_id)
        file = discord.File(io.BytesIO(data), filename="sachiko.png")
        await channel.send(file=file)
        logger.info(
            f"generate_image → #{getattr(channel, 'name', '?')}: {prompt[:60]!r}"
        )
        return {"ok": True, "sent": True}
