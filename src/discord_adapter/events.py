import discord

from core.bot_response import BotResponse
from core.bot_core import BotCore
from discord_adapter.message_parser import parse_message
from utils.logger import get_logger

logger = get_logger(__name__)

DISCORD_LIMIT = 2000


def _split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Discord 2000자 제한에 맞춰 줄 단위로 분할(긴 줄은 강제 분할)."""
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur:
        chunks.append(cur)
    return chunks or [text]


async def _reply_chunked(message: discord.Message, text: str) -> None:
    parts = _split_message(text)
    await message.reply(parts[0], suppress_embeds=True)
    for part in parts[1:]:
        await message.channel.send(part, suppress_embeds=True)


async def _include_referenced_attachments(
    message: discord.Message, request
) -> None:
    """답글 대상 메시지의 첨부도 현재 요청 첨부로 합친다."""
    if not message.reference or not message.reference.message_id:
        return

    referenced = message.reference.resolved
    if not isinstance(referenced, discord.Message):
        try:
            referenced = await message.channel.fetch_message(
                message.reference.message_id
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logger.warning(
                f"Failed to fetch referenced message "
                f"{message.reference.message_id}: {e}"
            )
            return

    if not referenced.attachments:
        return

    known_ids = {att.id for att in request.attachments}
    added = [att for att in referenced.attachments if att.id not in known_ids]
    if added:
        request.attachments.extend(added)
        logger.info(
            f"Referenced attachments included | "
            f"message={referenced.id} attachments={len(added)}"
        )


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
        await _include_referenced_attachments(message, request)

        channel_name = getattr(message.channel, "name", str(message.channel.id))
        logger.info(
            f"← #{channel_name} [{message.author.display_name}]: "
            f"{request.clean_content!r}"
        )

        async with message.channel.typing():
            try:
                response: BotResponse = await bot_core.handle(request)
                if response.message:
                    preview = response.message[:500].replace("\n", " ")
                    logger.info(f"→ #{channel_name}: {preview!r}")
                    await _reply_chunked(message, response.message)
                else:
                    logger.warning(f"Empty response for message {message.id}")
            except Exception as e:
                logger.error(f"Unhandled error: {e}", exc_info=True)
                await message.reply("뭔가 잘못됐어. 잠깐 뒤에 다시 해봐.")
