from storage.repositories import AffinityRepository
from utils.logger import get_logger

logger = get_logger(__name__)


def affinity_band(score: int) -> str:
    if score <= 25:
        return "싫어함"
    if score <= 50:
        return "그냥저냥"
    if score <= 75:
        return "좋아함"
    return "완전 좋아함"


class AffinityService:
    """유저별 호감도(0~100)를 관리한다. 매 요청마다 조회되므로 인메모리 캐싱."""

    def __init__(self) -> None:
        self._repo = AffinityRepository()
        self._cache: dict[tuple[int, int], int] = {}

    async def get(self, guild_id: int, user_id: int) -> int:
        key = (guild_id, user_id)
        if key not in self._cache:
            self._cache[key] = await self._repo.get(guild_id, user_id)
        return self._cache[key]

    async def adjust(self, guild_id: int, user_id: int, delta: int) -> int:
        new_score = await self._repo.adjust(guild_id, user_id, delta)
        self._cache[(guild_id, user_id)] = new_score
        logger.info(
            f"affinity | guild={guild_id} user={user_id} delta={delta:+d} → {new_score}"
        )
        return new_score
