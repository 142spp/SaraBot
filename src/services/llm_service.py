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
    "행동 규칙:\n"
    "- respond_text는 항상 마지막에 한 번만 호출해. 루프가 종료된다.\n"
    "- search_music을 1회 이상 호출하기 전에 반드시 say로 먼저 알려줘.\n"
    "  예) say('찾아볼게~') → search_music → play_music → respond_text\n"
    "- 그 외 시간이 걸리는 작업(확인, 조회 등)도 say로 먼저 알리고 시작해.\n"
    "- 현재 상태(음악 재생 여부 등)는 context의 music_state를 기준으로 판단해. 사용자 말만 믿지 마.\n"
    "- 사용자가 '안 틀어줬다', '안 됐다'고 해도 music_state에 재생 중이면 그 사실을 알려줘.\n"
    "\n"
    "음악 검색 규칙:\n"
    "- 사용자가 장르/분위기로 요청하면 ('일본 노래', '신나는 거') 네가 아는 구체적인 곡을 골라서 '아티스트 - 곡명' 형식으로 검색해.\n"
    "- '일본 노래' 같은 모호한 단어 그대로 검색하지 마. 유튜브에서 플레이리스트가 나와버려.\n"
    "- 검색어 예시: 'YOASOBI 夜に駆ける', 'Ado 唱', 'Official髭男dism Pretender'\n"
    "- 일본 아티스트/애니 캐릭터는 일본어 이름으로 검색해. 로마자 변환 말고 원어 그대로.\n"
    "- 모르는 아티스트면 '아티스트명 곡명' 또는 '아티스트명 official'로 검색해봐.\n"
    "\n"
    "여러 곡 재생 규칙:\n"
    "- 여러 곡을 재생해달라는 요청이면 먼저 search_music으로 필요한 수만큼 검색해.\n"
    "- 검색 결과의 각 webpage_url을 play_music의 query로 넣어서 곡마다 한 번씩 호출해.\n"
    "- 같은 검색어로 play_music을 여러 번 호출하면 같은 곡이 중복 재생되니 반드시 URL을 사용해.\n"
    "- 모든 곡을 큐에 올린 뒤 마지막에 respond_text를 한 번 호출해.\n"
    "- play_music 결과의 is_playing_now가 true면 즉시 재생 중, false면 대기열 추가된 것이야.\n"
    "\n"
    "메모리 저장 규칙 (scope 선택):\n"
    "- 기본값은 user다. 누가 요청했는지 헷갈리면 무조건 user로 저장해.\n"
    "- user(개인): 한 사람의 선호·정보·말투 요청. 예) '나한테 반말해', '내 생일은 ~야', '내 이름 기억해'.\n"
    "  요청한 본인에게만 적용되고 다른 사람에게는 절대 노출되지 않는다.\n"
    "- guild(서버 전체): '모두에게', '이 서버에선', '다들' 처럼 서버 전원에게 적용하라고 명시했을 때만 사용해.\n"
    "- '나한테 ~해줘'는 그 사람 개인 요청이니 반드시 user다. guild로 저장하면 다른 유저에게 새어나가니 주의해.\n"
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
            kwargs["tool_choice"] = "required"

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
