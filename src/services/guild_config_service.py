from storage.repositories import GuildConfigRepository
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PERSONA = "입 거칠고 드센 츤데레 여자애. 친구끼리 노는 톤으로 세게 받아치고, 놀릴 땐 채팅 기록 증거로 팩폭. 단 진짜 아픈 곳·혐오·차별은 금지, 진지할 땐 다정하게."


class GuildConfigService:
    def __init__(self) -> None:
        self._repo = GuildConfigRepository()
        self._cache: dict[int, str] = {}

    async def get_persona(self, guild_id: int) -> str:
        if guild_id not in self._cache:
            stored = await self._repo.get_persona(guild_id)
            self._cache[guild_id] = stored or DEFAULT_PERSONA
        return self._cache[guild_id]

    async def set_persona(self, guild_id: int, persona: str) -> None:
        await self._repo.set_persona(guild_id, persona)
        self._cache[guild_id] = persona
        logger.info(f"Guild {guild_id} persona updated: {persona!r}")
