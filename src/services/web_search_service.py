import httpx

import config
from utils.logger import get_logger

logger = get_logger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT = 15
MAX_CONTENT_CHARS = 500  # 결과 본문 1개당 상한 (토큰 절약)


class WebSearchService:
    """Tavily 웹 검색. 결과를 LLM이 답변에 쓰기 좋은 형태로 반환한다."""

    async def search(self, query: str, max_results: int = 5) -> dict:
        if not config.TAVILY_API_KEY:
            return {"ok": False, "error": "웹 검색 비활성(API 키 미설정)"}
        query = (query or "").strip()
        if not query:
            return {"ok": False, "error": "검색어가 비어있어"}

        payload = {
            "api_key": config.TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(TAVILY_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning(f"web_search error: {e}")
            return {"ok": False, "error": f"검색 실패: {e}"}

        results = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": (r.get("content") or "")[:MAX_CONTENT_CHARS],
            }
            for r in data.get("results", [])
        ]
        logger.info(f"web_search | {query[:60]!r} → {len(results)} results")
        return {
            "ok": True,
            "query": query,
            "answer": data.get("answer"),
            "results": results,
        }
