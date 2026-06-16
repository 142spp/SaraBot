import discord

from core.bot_core import BotCore
from discord_adapter.message_parser import parse_message
from utils.logger import get_logger

logger = get_logger(__name__)


def register_events(client: discord.Client, bot_core: BotCore) -> None:
    @client.event
    async def on_ready() -> None:
        logger.info(f"Logged in as {client.user} (id: {client.user.id})")
        logger.debug(f"Guilds: {[g.name for g in client.guilds]}")

    @client.event
    async def on_message(message: discord.Message) -> None:
        request = parse_message(message, client.user)
        if request is None:
            return

        channel_name = getattr(message.channel, "name", str(message.channel.id))
        logger.info(
            f"← #{channel_name} [{message.author.display_name}]: "
            f"{request.clean_content!r}"
        )

        async with message.channel.typing():
            try:
                response = await bot_core.handle(request)
                if response:
                    preview = response[:100].replace("\n", " ")
                    logger.info(f"→ #{channel_name}: {preview!r}")
                    await message.reply(response)
                else:
                    logger.warning(f"Empty response for message {message.id}")
            except Exception as e:
                logger.error(f"Unhandled error: {e}", exc_info=True)
                await message.reply("뭔가 잘못됐어. 잠깐 뒤에 다시 해봐.")
