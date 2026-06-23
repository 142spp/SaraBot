from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any


MAX_ITEMS_PER_CHANNEL = 12
MAX_TEXT_CHARS = 1800
MAX_RESULT_CHARS = 3000
REMEMBER_TOOL_RESULTS = {
    "run_sql",
    "search_chat_history",
    "analyze_user",
    "summarize_recent_chat",
    "recall_this_day",
}


class ConversationMemoryService:
    """채널별 최근 에이전트 관찰값을 인메모리로 보관한다.

    DB 메모리처럼 영구 보존할 사실이 아니라, 직전 검색/분석/이미지 이해 같은
    대화 흐름 보강용 컨텍스트다. 봇 재시작 시 사라지는 것이 정상이다.
    """

    def __init__(self) -> None:
        self._items: dict[int, deque[dict]] = defaultdict(
            lambda: deque(maxlen=MAX_ITEMS_PER_CHANNEL)
        )

    def add_tool_result(
        self,
        channel_id: int,
        tool_name: str,
        args: dict,
        result: dict,
    ) -> None:
        if tool_name not in REMEMBER_TOOL_RESULTS:
            return
        self._items[channel_id].append(
            {
                "type": "tool_result",
                "at": self._now(),
                "tool": tool_name,
                "args": self._truncate(args, MAX_TEXT_CHARS),
                "result": self._truncate(result, MAX_RESULT_CHARS),
            }
        )

    def add_final_response(
        self,
        channel_id: int,
        user_message: str,
        response: str,
        *,
        saw_images: bool = False,
    ) -> None:
        self._items[channel_id].append(
            {
                "type": "assistant_response",
                "at": self._now(),
                "user_message": user_message[:MAX_TEXT_CHARS],
                "response": response[:MAX_TEXT_CHARS],
                "saw_images": saw_images,
            }
        )

    def add_image_analysis(self, channel_id: int, description: str) -> None:
        """이미지가 첨부됐을 때 모델이 남긴 객관적 묘사를 박제한다.
        이미지는 다음 턴이면 사라지므로, 질문에 갇히지 않은 전체 내용을 보존한다."""
        description = (description or "").strip()
        if not description:
            return
        self._items[channel_id].append(
            {
                "type": "image_analysis",
                "at": self._now(),
                "description": description[:MAX_TEXT_CHARS],
            }
        )

    def list_recent(self, channel_id: int) -> list[dict]:
        return list(self._items.get(channel_id, ()))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _truncate(self, value: Any, limit: int) -> Any:
        if isinstance(value, str):
            return value[:limit]
        if isinstance(value, dict):
            return {
                str(k): self._truncate(v, limit)
                for k, v in list(value.items())[:30]
            }
        if isinstance(value, list):
            return [self._truncate(v, limit) for v in value[:20]]
        return value
