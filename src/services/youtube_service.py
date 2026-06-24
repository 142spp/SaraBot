import asyncio
import re

import httpx
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)
from youtube_transcript_api._errors import CouldNotRetrieveTranscript

from services.llm_service import LLMService
from utils.logger import get_logger

logger = get_logger(__name__)

# youtube.com/watch?v=, youtu.be/, shorts/, embed/ 등에서 11자리 video id 추출
_ID_PATTERNS = [
    re.compile(r"(?:v=|/shorts/|/embed/|youtu\.be/)([A-Za-z0-9_-]{11})"),
]
OEMBED_URL = "https://www.youtube.com/oembed"
# 자막 언어 우선순위 (한국어 → 영어)
LANGS = ["ko", "en"]
# 요약 LLM에 넣을 자막 길이 상한 (토큰 폭발 방지). 대략 40분 영상 분량.
MAX_TRANSCRIPT_CHARS = 15000


def extract_video_id(text: str) -> str | None:
    for pat in _ID_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


class YouTubeService:
    """유튜브 자막을 긁어 LLM으로 객관 요약한다. (음성 다운로드/전사는 안 함)"""

    def __init__(self, llm_service: LLMService) -> None:
        self._llm = llm_service
        self._api = YouTubeTranscriptApi()

    async def summarize(self, url: str) -> dict:
        video_id = extract_video_id(url)
        if not video_id:
            return {"ok": False, "error": "유튜브 링크가 아니거나 영상 ID를 못 찾았어."}

        try:
            transcript = await asyncio.to_thread(self._fetch_transcript, video_id)
        except (TranscriptsDisabled, NoTranscriptFound):
            return {"ok": False, "error": "이 영상은 자막이 없어서 내용을 못 봐."}
        except VideoUnavailable:
            return {"ok": False, "error": "영상을 못 불러와(비공개/삭제/지역제한)."}
        except CouldNotRetrieveTranscript as e:
            logger.warning(f"youtube transcript error: {e}")
            return {"ok": False, "error": "자막을 가져오지 못했어."}
        except Exception as e:
            logger.warning(f"youtube unexpected error: {e}")
            return {"ok": False, "error": f"자막 처리 실패: {e}"}

        if not transcript.strip():
            return {"ok": False, "error": "자막이 비어있어서 요약할 게 없어."}

        title, author = await self._fetch_meta(video_id)
        truncated = len(transcript) > MAX_TRANSCRIPT_CHARS
        body = transcript[:MAX_TRANSCRIPT_CHARS]

        summary = await self._summarize_text(title, body, truncated)
        logger.info(
            f"youtube summarize | id={video_id} title={title!r} "
            f"chars={len(transcript)} truncated={truncated}"
        )
        return {
            "ok": True,
            "video_id": video_id,
            "title": title,
            "author": author,
            "summary": summary,
            "truncated": truncated,
        }

    def _fetch_transcript(self, video_id: str) -> str:
        """blocking. ko→en 우선, 없으면 아무 자막이나(가능하면 ko 번역)."""
        try:
            fetched = self._api.fetch(video_id, languages=LANGS)
        except NoTranscriptFound:
            tlist = self._api.list(video_id)
            picked = next(iter(tlist))  # 사용 가능한 첫 자막
            if picked.is_translatable:
                try:
                    picked = picked.translate("ko")
                except Exception:
                    pass
            fetched = picked.fetch()
        parts = [snip.text.strip() for snip in fetched if snip.text.strip()]
        return " ".join(parts)

    async def _fetch_meta(self, video_id: str) -> tuple[str, str]:
        """oembed로 제목·채널명만 가볍게 (실패해도 무시)."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    OEMBED_URL, params={"url": url, "format": "json"}
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("title") or "제목 미상", data.get("author_name") or ""
        except Exception:
            return "제목 미상", ""

    async def _summarize_text(self, title: str, body: str, truncated: bool) -> str:
        note = "\n(자막이 길어서 앞부분만 봤어.)" if truncated else ""
        prompt = (
            "다음은 유튜브 영상의 자막이야. 이 영상이 무슨 내용인지 한국어로 "
            "객관적으로 요약해줘. 핵심 주제와 주요 포인트를 3~6개 불릿으로, "
            "과장·추측 없이 자막에 있는 내용만. 말투는 평범하게.\n"
            f"\n영상 제목: {title}{note}\n\n자막:\n{body}"
        )
        return (await self._llm.judge(prompt)).strip()
