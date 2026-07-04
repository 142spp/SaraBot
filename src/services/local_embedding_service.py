import asyncio

from utils.logger import get_logger

logger = get_logger(__name__)

BGE_M3_MODEL = "BAAI/bge-m3"
BGE_M3_DIM = 1024
DEFAULT_BATCH_SIZE = 64


class LocalEmbeddingService:
    def __init__(
        self,
        model_name: str = BGE_M3_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading local embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def run() -> list[list[float]]:
            model = self._load_model()
            vectors = model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return vectors.tolist()

        vectors = await asyncio.to_thread(run)
        logger.debug(f"Local embedded {len(texts)} text(s) with {self._model_name}")
        return vectors

    @staticmethod
    def to_pgvector(embedding: list[float]) -> str:
        return "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"
