from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PERSONA = "귀엽고 친근한 여자애처럼 행동해. 반말로 대화해도 돼."


class GuildConfigService:
    """서버별 설정을 관리한다. v0.5에서 DB로 교체 예정."""

    def __init__(self) -> None:
        self._personas: dict[int, str] = {}

    def get_persona(self, guild_id: int) -> str:
        return self._personas.get(guild_id, DEFAULT_PERSONA)

    def set_persona(self, guild_id: int, persona: str) -> None:
        self._personas[guild_id] = persona
        logger.info(f"Guild {guild_id} persona updated: {persona!r}")
