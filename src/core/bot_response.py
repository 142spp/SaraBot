from dataclasses import dataclass, field


@dataclass
class BotResponse:
    message: str
    embeds: list[dict] = field(default_factory=list)
