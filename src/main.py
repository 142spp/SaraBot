import asyncio

import discord

import config
from utils.logger import setup_logging

setup_logging()

from core.agent import Agent
from core.bot_core import BotCore
from core.context_builder import ContextBuilder
from core.policy import PolicyLayer
from core.tool_executor import ToolExecutor
from discord_adapter.events import register_events
from services.llm_service import LLMService
from services.music_service import MusicService
from services.voice_service import VoiceService
from tools.chat_tools import RespondTextTool
from tools.music_tools import PlayMusicTool, SearchMusicTool, ShowQueueTool, SkipMusicTool
from tools.voice_tools import GetUserVoiceChannelTool, JoinVoiceTool, LeaveVoiceTool
from utils.logger import get_logger

logger = get_logger(__name__)


async def main() -> None:
    if not config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set")
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.voice_states = True
    client = discord.Client(intents=intents)

    voice_service = VoiceService(client)
    music_service = MusicService(client)
    llm_service = LLMService()
    policy = PolicyLayer(client)
    tool_executor = ToolExecutor([
        RespondTextTool(),
        GetUserVoiceChannelTool(voice_service),
        JoinVoiceTool(voice_service),
        LeaveVoiceTool(voice_service),
        SearchMusicTool(music_service),
        PlayMusicTool(music_service, voice_service),
        SkipMusicTool(music_service),
        ShowQueueTool(music_service),
    ])

    context_builder = ContextBuilder(client, music_service)
    agent = Agent(context_builder, llm_service, policy, tool_executor)
    bot_core = BotCore(agent)

    register_events(client, bot_core)

    logger.info("Starting Sachiko bot...")
    await client.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
