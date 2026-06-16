import discord

from core.bot_core import BotCore
from discord_adapter.events import register_events


def create_client(bot_core: BotCore) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.voice_states = True

    client = discord.Client(intents=intents)
    register_events(client, bot_core)
    return client
