from discord_adapter.message_parser import BotRequest


class PolicyResult:
    def __init__(self, ok: bool, reason: str = "") -> None:
        self.ok = ok
        self.reason = reason


class PolicyLayer:
    async def check(
        self, request: BotRequest, tool_name: str, args: dict
    ) -> PolicyResult:
        return PolicyResult(ok=True)
