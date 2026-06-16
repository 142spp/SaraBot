from storage.repositories import GuildConfigRepository
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PERSONA = "귀엽고 친근한 여자애처럼 행동해. 반말로 대화해도 돼."


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
