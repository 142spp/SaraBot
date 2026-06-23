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
        """프롬프트로 이미지를 생성해 PNG 바이트로 반환. 실패 시 None."""
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

        if not resp.data:
            return None
        b64 = resp.data[0].b64_json
        if not b64:
            return None
        return base64.b64decode(b64)
