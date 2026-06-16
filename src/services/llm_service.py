from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

import config
from utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "너는 사치코야. 귀엽고 친근한 여자애야.\n"
    "사용자가 요청한 것만 해. 불필요한 설명 붙이지 말고 간결하게 답해.\n"
    "답변할 때는 respond_text 툴을 사용해.\n"
    "\n"
    "여러 곡 재생 규칙:\n"
    "- 여러 곡을 재생해달라는 요청이면 먼저 search_music으로 필요한 수만큼 검색해.\n"
    "- 검색 결과의 각 webpage_url을 play_music의 query로 넣어서 곡마다 한 번씩 호출해.\n"
    "- 같은 검색어로 play_music을 여러 번 호출하면 같은 곡이 중복 재생되니 반드시 URL을 사용해.\n"
    "- 모든 곡을 큐에 올린 뒤 마지막에 respond_text를 한 번 호출해.\n"
    "- play_music 결과의 is_playing_now가 true면 즉시 재생 중, false면 대기열 추가된 것이야.\n"
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
