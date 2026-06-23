import base64

from openai import AsyncOpenAI

import config
from utils.logger import get_logger

logger = get_logger(__name__)

IMAGE_MODEL = "gpt-image-2"  # gpt-image-1보다 출력 토큰 단가 저렴($30 vs $32/1M)
IMAGE_SIZE = "1024x1024"
IMAGE_QUALITY = "medium"  # low / medium / high — medium ≈ 장당 45원


class ImageService:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    async def generate(self, prompt: str) -> bytes | None:
        """프롬프트로 이미지를 새로 생성해 PNG 바이트로 반환. 실패 시 None."""
        try:
            resp = await self._client.images.generate(
                model=IMAGE_MODEL,
                prompt=prompt,
                size=IMAGE_SIZE,
                quality=IMAGE_QUALITY,
                n=1,
            )
        except Exception as e:
            logger.warning(f"image generate error: {e}")
            return None
        return self._extract(resp)

    async def edit(self, prompt: str, files: list[tuple]) -> bytes | None:
        """입력 이미지(들)를 바탕으로 편집/변형해 PNG 바이트로 반환. 실패 시 None.
        files: (filename, bytes, content_type) 튜플 목록."""
        try:
            resp = await self._client.images.edit(
                model=IMAGE_MODEL,
                image=files,
                prompt=prompt,
                size=IMAGE_SIZE,
                quality=IMAGE_QUALITY,
                n=1,
            )
        except Exception as e:
            logger.warning(f"image edit error: {e}")
            return None
        return self._extract(resp)

    @staticmethod
    def _extract(resp) -> bytes | None:
        if not resp.data:
            return None
        b64 = resp.data[0].b64_json
        if not b64:
            return None
        return base64.b64decode(b64)
