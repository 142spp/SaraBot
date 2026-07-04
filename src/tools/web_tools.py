from services.web_search_service import WebSearchService
from tools.base import BaseTool

MAX_RESULTS = 8


class WebSearchTool(BaseTool):
    def __init__(self, web_search_service: WebSearchService) -> None:
        self._svc = web_search_service

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "인터넷에서 최신/외부 정보를 검색한다. 날씨·뉴스·시세·스포츠 결과·"
                    "모르는 사람/용어/제품 등 채팅 기록 밖의 정보가 필요할 때 사용. "
                    "상위 출처는 evidence_markdown으로 함께 돌려준다. "
                    "respond_text에서는 results/evidence_markdown의 실제 제목·URL·발행일을 "
                    "답변 본문 안에 자연스럽게 섞어라. "
                    "별도의 하단 출처 섹션으로 몰아넣지 마라. 없는 출처는 만들지 마라. "
                    "(서버 채팅 기록 검색은 search_chat_history를 쓴다.)"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "검색어. 핵심 키워드 위주로 간결하게.",
                        },
                        "max_results": {
                            "type": "integer",
                            "default": 5,
                            "description": "가져올 결과 수 (최대 8)",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query가 비어있어. 검색어를 채워서 호출해."}
        max_results = min(int(args.get("max_results", 5)), MAX_RESULTS)
        return await self._svc.search(query, max_results)
