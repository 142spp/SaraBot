import json

from core.context_builder import ContextBuilder
from core.policy import PolicyLayer
from core.tool_executor import ToolExecutor
from discord_adapter.message_parser import BotRequest
from services.llm_service import LLMService
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_AGENT_STEPS = 10
TERMINAL_TOOLS = {"respond_text"}


class Agent:
    def __init__(
        self,
        context_builder: ContextBuilder,
        llm_service: LLMService,
        policy: PolicyLayer,
        tool_executor: ToolExecutor,
    ) -> None:
        self._context_builder = context_builder
        self._llm = llm_service
        self._policy = policy
        self._executor = tool_executor

    async def run(self, request: BotRequest) -> str:
        context = await self._context_builder.build(request)
        logger.debug(f"Context built | {json.dumps(context, ensure_ascii=False)}")

        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    f"[현재 상태]\n{context_str}\n\n"
                    f"[사용자 요청]\n{request.clean_content or '(내용 없음)'}"
                ),
            }
        ]
        tools = self._executor.get_definitions()

        for step in range(1, MAX_AGENT_STEPS + 1):
            logger.info(f"Agent step {step}/{MAX_AGENT_STEPS}")
            response = await self._llm.call(messages=messages, tools=tools)

            if not response.tool_calls:
                logger.info("Agent done | direct response (no tool calls)")
                return response.content or "..."


            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in response.tool_calls
                    ],
                }
            )

            for tc in response.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                logger.info(f"Tool call | {tool_name}({args})")

                policy_result = await self._policy.check(request, tool_name, args)
                if not policy_result.ok:
                    logger.warning(f"Policy denied | {tool_name}: {policy_result.reason}")
                    result = {"ok": False, "error": policy_result.reason}
                else:
                    result = await self._executor.execute(request, tool_name, args)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

                if tool_name in TERMINAL_TOOLS and result.get("ok"):
                    msg = result.get("message", "")
                    logger.info(f"Agent done | terminal tool={tool_name}")
                    return msg

        logger.warning(f"Agent step limit reached ({MAX_AGENT_STEPS})")
        return "요청을 처리하다가 단계가 너무 길어져서 중단했어."
