from tools.base import BaseTool
from discord_adapter.message_parser import BotRequest
from utils.logger import get_logger

logger = get_logger(__name__)


class ToolExecutor:
    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    async def execute(self, request: BotRequest, tool_name: str, args: dict) -> dict:
        tool = self._tools.get(tool_name)
        if not tool:
            logger.warning(f"Unknown tool requested: {tool_name!r}")
            return {"ok": False, "error": f"unknown tool: {tool_name}"}

        logger.debug(f"Tool execute | {tool_name} args={args}")
        try:
            result = await tool.execute(args, request)
            logger.debug(f"Tool result  | {tool_name} → {result}")
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} raised: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    def get_definitions(self) -> list[dict]:
        return [tool.definition for tool in self._tools.values()]
