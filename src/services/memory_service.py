from storage.repositories import MemoryRepository
from utils.logger import get_logger

logger = get_logger(__name__)

ALLOWED_SCOPES = {"user", "guild"}


class MemoryService:
    def __init__(self) -> None:
        self._repo = MemoryRepository()

    async def remember(self, scope: str, scope_id: int, content: str) -> int:
        if scope not in ALLOWED_SCOPES:
            raise ValueError(f"Invalid scope: {scope}")
        return await self._repo.save(scope, scope_id, content)

    async def forget(self, scope: str, scope_id: int, memory_id: int) -> bool:
        if scope not in ALLOWED_SCOPES:
            raise ValueError(f"Invalid scope: {scope}")
        return await self._repo.delete(scope, scope_id, memory_id)

    async def list(self, scope: str, scope_id: int) -> list[dict]:
        return await self._repo.list(scope, scope_id)
