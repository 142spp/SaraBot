from core.agent import Agent
from discord_adapter.message_parser import BotRequest
from utils.logger import get_logger

logger = get_logger(__name__)


class BotCore:
    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    async def handle(self, request: BotRequest) -> str:
        logger.info(
            f"[{request.guild_id}] {request.display_name}: {request.clean_content!r}"
        )
        return await self._agent.run(request)
