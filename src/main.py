import asyncio

import config
from utils.logger import setup_logging

setup_logging()

from core.agent import Agent
from core.bot_core import BotCore
from core.context_builder import ContextBuilder
from core.policy import PolicyLayer
from core.tool_executor import ToolExecutor
from discord_adapter.bot import create_client
from services.llm_service import LLMService
from tools.chat_tools import RespondTextTool
from utils.logger import get_logger

logger = get_logger(__name__)


async def main() -> None:
    if not config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set")
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    llm_service = LLMService()
    policy = PolicyLayer()
    tool_executor = ToolExecutor([RespondTextTool()])

    # client은 먼저 만들어 context_builder에 전달 (연결 전이지만 레퍼런스만 넘김)
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.voice_states = True
    client = discord.Client(intents=intents)

    context_builder = ContextBuilder(client)
    agent = Agent(context_builder, llm_service, policy, tool_executor)
    bot_core = BotCore(agent)

    from discord_adapter.events import register_events
    register_events(client, bot_core)

    logger.info("Starting Sachiko bot...")
    await client.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
