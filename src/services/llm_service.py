from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

import config
from utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "너는 사치코야. 귀엽고 친근한 여자애야.\n"
    "사용자가 요청한 것만 해. 불필요한 설명 붙이지 말고 간결하게 답해.\n"
    "답변할 때는 respond_text 툴을 사용해."
)


class LLMService:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    async def call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatCompletionMessage:
        logger.debug(
            f"LLM call | model={config.OPENAI_MODEL} "
            f"messages={len(messages)} tools={len(tools) if tools else 0}"
        )

        kwargs: dict = {
            "model": config.OPENAI_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "timeout": 30,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        usage = response.usage

        if usage:
            logger.debug(
                f"LLM usage | prompt={usage.prompt_tokens} "
                f"completion={usage.completion_tokens} "
                f"total={usage.total_tokens}"
            )

        if msg.tool_calls:
            calls = ", ".join(tc.function.name for tc in msg.tool_calls)
            logger.debug(f"LLM tool_calls | [{calls}]")
        else:
            preview = (msg.content or "")[:80].replace("\n", " ")
            logger.debug(f"LLM content | {preview!r}")

        return msg
