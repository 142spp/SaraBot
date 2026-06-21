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
                "description": (
                    "사용자가 기억해달라고 한 개인 선호나 서버 설정을 저장한다. "
                    "scope 선택이 중요하다. 기본은 user이며, 헷갈리면 user를 써라."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "scope": {
                            "type": "string",
                            "enum": ["user", "guild"],
                            "description": (
                                "user: 요청한 본인에게만 적용되는 개인 선호/정보. "
                                "다른 유저에게 노출되지 않는다. '나한테 ~해줘'는 항상 user. "
                                "guild: 서버 전원에게 공유되는 설정. "
                                "'모두에게', '이 서버에선' 처럼 전체 적용을 명시했을 때만 사용."
                            ),
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
