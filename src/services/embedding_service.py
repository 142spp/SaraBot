from openai import AsyncOpenAI

import config
from utils.logger import get_logger

logger = get_logger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
BATCH_SIZE = 256  # 청크가 길어도 요청당 토큰 한도(~30만) 안 넘게 보수적으로


class EmbeddingService:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 리스트를 임베딩 벡터 리스트로 변환한다."""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            resp = await self._client.embeddings.create(
                model=EMBEDDING_MODEL, input=batch
            )
            vectors.extend(d.embedding for d in resp.data)
        logger.debug(f"Embedded {len(texts)} texts → {len(vectors)} vectors")
        return vectors

    @staticmethod
    def to_pgvector(embedding: list[float]) -> str:
        """asyncpg가 vector 타입을 모르므로 '[...]' 문자열로 변환해 ::vector 캐스팅."""
        return "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"
