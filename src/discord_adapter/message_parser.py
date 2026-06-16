from dataclasses import dataclass, field

import discord


@dataclass
class BotRequest:
    guild_id: int
    channel_id: int
    message_id: int
    user_id: int
    display_name: str
    content: str
    clean_content: str
    is_admin: bool
    user_voice_channel_id: int | None
    replied_message_id: int | None
    attachments: list = field(default_factory=list)


def parse_message(
    message: discord.Message, bot_user: discord.ClientUser
) -> BotRequest | None:
    if not message.guild:
        return None
    if message.author.bot:
        return None
    if bot_user not in message.mentions:
        return None

    clean_content = message.content
    for mention in message.mentions:
        clean_content = clean_content.replace(f"<@{mention.id}>", "")
        clean_content = clean_content.replace(f"<@!{mention.id}>", "")
    clean_content = clean_content.strip()

    member = message.author
    is_admin = (
        isinstance(member, discord.Member)
        and member.guild_permissions.administrator
    )

    user_voice_channel_id: int | None = None
    if isinstance(member, discord.Member) and member.voice and member.voice.channel:
        user_voice_channel_id = member.voice.channel.id

    replied_message_id: int | None = None
    if message.reference:
        replied_message_id = message.reference.message_id

    display_name = (
        member.display_name if isinstance(member, discord.Member) else message.author.name
    )

    return BotRequest(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        message_id=message.id,
        user_id=message.author.id,
        display_name=display_name,
        content=message.content,
        clean_content=clean_content,
        is_admin=is_admin,
        user_voice_channel_id=user_voice_channel_id,
        replied_message_id=replied_message_id,
        attachments=list(message.attachments),
    )
