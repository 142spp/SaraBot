import httpx

import config
from utils.logger import get_logger

logger = get_logger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT = 15
MAX_CONTENT_CHARS = 500  # 결과 본문 1개당 상한 (토큰 절약)
MAX_EMBED_CONTENT_CHARS = 260


def _clip(text: str, max_chars: int = MAX_EMBED_CONTENT_CHARS) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _web_evidence_embeds(results: list[dict], limit: int = 3) -> list[dict]:
    embeds: list[dict] = []
    for index, item in enumerate(results[:limit], start=1):
        url = item.get("url")
        if not url:
            continue
        fields = [{"name": "출처", "value": f"[원문 보기]({url})", "inline": False}]
        if item.get("published_date"):
            fields.insert(
                0,
                {
                    "name": "발행일",
                    "value": str(item["published_date"]),
                    "inline": True,
                },
            )
        embeds.append(
            {
                "title": f"웹 근거 {index} · {item.get('title') or '출처'}",
                "url": url,
                "description": _clip(item.get("content") or ""),
                "fields": fields,
                "footer": "web_search",
            }
        )
    return embeds


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
                "published_date": r.get("published_date"),
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
            "evidence_embeds": _web_evidence_embeds(results),
        }
