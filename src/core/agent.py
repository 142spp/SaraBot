import json

from core.context_builder import ContextBuilder
from core.policy import PolicyLayer
from core.tool_executor import ToolExecutor
from discord_adapter.message_parser import BotRequest
from services.llm_service import LLMService
from services.conversation_memory_service import ConversationMemoryService
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
        conversation_memory: ConversationMemoryService | None = None,
    ) -> None:
        self._context_builder = context_builder
        self._llm = llm_service
        self._policy = policy
        self._executor = tool_executor
        self._conversation_memory = conversation_memory

    @staticmethod
    def _build_history_turns(recent: list[dict]) -> list[dict]:
        """recent_messages를 user/assistant 턴 목록으로 변환한다.
        봇 발언은 assistant, 사람 발언은 '[이름] 내용' 형태의 user 턴."""
        turns: list[dict] = []
        for m in recent:
            text = (m.get("content") or "").strip()
            if m.get("is_bot"):
                if not text:  # 봇의 빈 메시지(임베드 전용 등)는 건너뜀
                    continue
                turns.append({"role": "assistant", "content": text})
            else:
                if not text:  # 사람의 이미지/첨부만 있는 메시지
                    text = "[이미지/첨부]"
                author = m.get("author") or "누군가"
                turns.append({"role": "user", "content": f"[{author}] {text}"})
        return turns

    async def run(self, request: BotRequest) -> str:
        context = await self._context_builder.build(request)
        logger.debug(f"Context built | {json.dumps(context, ensure_ascii=False)}")

        # 최근 대화는 JSON 블록이 아니라 실제 user/assistant 턴으로 펼쳐 전달한다.
        # (봇 발언=assistant, 사람=이름 prefix를 단 user) — 모델이 맥락을 훨씬 잘 잡는다.
        recent = context.pop("recent_messages", [])
        history_turns = self._build_history_turns(recent)

        # 상태 JSON(music_state·memories·recent_observations 등)은 '지금 시점' 정보라
        # 과거 턴이 아니라 마지막 현재 턴에만 붙인다.
        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        text_block = (
            f"[현재 상태]\n{context_str}\n\n"
            f"[사용자 요청]\n[{request.display_name}] {request.clean_content or '(내용 없음)'}"
        )

        image_urls = self._context_builder.collect_image_urls(request)

        user_content: str | list[dict]
        if image_urls:
            logger.info(f"Vision | {len(image_urls)} image(s) attached")
            user_content = [{"type": "text", "text": text_block}]
            for url in image_urls:
                user_content.append({"type": "image_url", "image_url": {"url": url}})
        else:
            user_content = text_block

        messages: list[dict] = history_turns + [
            {"role": "user", "content": user_content}
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

                if self._conversation_memory:
                    self._conversation_memory.add_tool_result(
                        request.channel_id, tool_name, args, result
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

                if tool_name in TERMINAL_TOOLS and result.get("ok"):
                    msg = result.get("message", "")
                    if self._conversation_memory:
                        self._conversation_memory.add_final_response(
                            request.channel_id,
                            request.clean_content,
                            msg,
                            saw_images=bool(image_urls),
                        )
                        # 이미지에 대한 객관 묘사를 같은 호출에서 받아 박제(추가 호출 없음)
                        if image_urls and result.get("image_notes"):
                            self._conversation_memory.add_image_analysis(
                                request.channel_id, result["image_notes"]
                            )
                            logger.info("Image analysis stored")
                    logger.info(f"Agent done | terminal tool={tool_name}")
                    return msg

        logger.warning(f"Agent step limit reached ({MAX_AGENT_STEPS})")
        return "요청을 처리하다가 단계가 너무 길어져서 중단했어."
