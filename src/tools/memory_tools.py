from services.memory_service import MemoryService
from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)


class RememberUserPreferenceTool(BaseTool):
    def __init__(self, memory_service: MemoryService) -> None:
        self._memory = memory_service

    @property
    def name(self) -> str:
        return "remember_user_preference"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "remember_user_preference",
                "description": "사용자가 명시적으로 기억해달라고 한 개인 선호나 서버 설정을 저장한다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "scope": {
                            "type": "string",
                            "enum": ["user", "guild"],
                            "description": "user: 개인 선호, guild: 서버 전체 설정",
                        },
                    },
                    "required": ["content", "scope"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        scope = args["scope"]
        scope_id = request.user_id if scope == "user" else request.guild_id
        try:
            memory_id = await self._memory.remember(scope, scope_id, args["content"])
            return {"ok": True, "memory_id": memory_id}
        except Exception as e:
            logger.error(f"remember failed: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}


class ForgetUserMemoryTool(BaseTool):
    def __init__(self, memory_service: MemoryService) -> None:
        self._memory = memory_service

    @property
    def name(self) -> str:
        return "forget_user_memory"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "forget_user_memory",
                "description": "저장된 memory를 삭제한다. memory_id는 remember_user_preference 응답에서 받은 값을 쓴다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer"},
                        "scope": {"type": "string", "enum": ["user", "guild"]},
                    },
                    "required": ["memory_id", "scope"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        scope = args["scope"]
        scope_id = request.user_id if scope == "user" else request.guild_id
        try:
            deleted = await self._memory.forget(scope, scope_id, int(args["memory_id"]))
            if not deleted:
                return {"ok": False, "error": "MEMORY_NOT_FOUND"}
            return {"ok": True}
        except Exception as e:
            logger.error(f"forget failed: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}
