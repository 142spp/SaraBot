import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.message_archive_service import MessageArchiveService
from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)


KST = ZoneInfo("Asia/Seoul")


def _parse_kst_date_range(text: str):
    match = re.search(
        r"(\d{2,4})\s*년\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?",
        text,
    )
    if not match:
        return None, None

    year = int(match.group(1))
    if year < 100:
        year += 2000
    month = int(match.group(2))
    day = int(match.group(3)) if match.group(3) else None
    if day:
        start = datetime(year, month, day, tzinfo=KST)
        end = start + timedelta(days=1)
    else:
        start = datetime(year, month, 1, tzinfo=KST)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=KST)
        else:
            end = datetime(year, month + 1, 1, tzinfo=KST)
    return start, end


class IngestChannelHistoryTool(BaseTool):
    def __init__(self, archive_service: MessageArchiveService) -> None:
        self._archive = archive_service

    @property
    def name(self) -> str:
        return "ingest_channel_history"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "ingest_channel_history",
                "description": (
                    "현재 채널의 전체 대화 기록을 DB에 저장한다. "
                    "이미 저장된 기록이 있으면 그 이후 메시지만 추가(증분)한다. "
                    "메시지가 많으면 수십 초~몇 분 걸리니 호출 전 say로 먼저 알려라. "
                    "진행 상황은 이 툴이 직접 embed로 채팅에 실시간 표시하므로 "
                    "respond_text에서 저장 개수를 다시 말할 필요 없다. "
                    "사용자가 '채널 기록 저장', '대화 다 기억해' 등을 요청할 때 사용."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        return await self._archive.ingest_channel(request.channel_id)


class SearchChatHistoryTool(BaseTool):
    def __init__(self, archive_service: MessageArchiveService) -> None:
        self._archive = archive_service

    @property
    def name(self) -> str:
        return "search_chat_history"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "search_chat_history",
                "description": (
                    "현재 채널의 과거 대화 기록을 검색한다. "
                    "사용자가 '예전에 ~한 얘기', '언제 ~했어?', '~에 대해 뭐라고 했지?' 처럼 "
                    "과거 대화를 물어볼 때 사용. "
                    "두 가지 결과를 함께 돌려준다: "
                    "keyword_matches(핵심 단어가 들어간 개별 메시지), "
                    "hybrid_matches(키워드 검색과 의미 검색을 합쳐 재정렬한 대화 덩어리). "
                    "둘 다 참고해서 답해라. 돌려 말한 질문도 hybrid_matches가 관련 대화를 찾아준다. "
                    "상위 근거는 evidence_markdown으로 함께 돌려준다. "
                    "검색 결과의 source_url/context_sources는 원본 Discord 메시지 근거다. "
                    "respond_text에서는 핵심 요약만 말해라. 근거 마크다운은 시스템이 자동으로 붙인다. "
                    "query에는 검색 대상인 고유명사·작품명·사람명·음식명·핵심 명사만 넣어라. "
                    "'예전에', '얘기', '기록', '찾아줘', '언제', '누가' 같은 요청어·조사·동사는 빼라. "
                    "OR/AND 같은 연산자를 쓰지 말고 핵심어만 공백으로 나열해라. "
                    "예: '예전에 코드기어스 얘기했던 거 찾아줘' -> query='코드기어스'. "
                    "예: '뉴진스 얘기한 것도 찾아봐' -> query='뉴진스'. "
                    "예: '아쌔이가 25년12월11일에 뉴진스 얘기했어?' -> query='뉴진스', author='아쌔이'. "
                    "author는 현재 사용자 요청 문장에 특정 작성자 이름이 직접 나오거나 "
                    "'내가/내 기록'처럼 요청자 본인을 명시할 때만 넣어라. "
                    "사용자가 단순히 '~ 얘기 찾아봐'라고 하면 author를 절대 넣지 마라. "
                    "'~ 기록 찾아줘'도 요청자가 말한 기록이라는 뜻으로 추론하지 말고 author를 비워라. "
                    "'누가 무슨 얘기했어?'처럼 말한 사람을 찾아야 하는 질문이면 author를 비워라. "
                    "결과의 시간(created_at/start_at)으로 '언제' 질문에 답할 수 있다. "
                    "검색 전 최신 기록까지 자동 갱신되며, 첫 사용 시 시간이 걸릴 수 있으니 say로 먼저 알려라."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "검색 키워드. 여러 단어는 AND로 묶인다. 비워도 된다.",
                        },
                        "author": {
                            "type": "string",
                            "description": "작성자 이름(부분일치). 특정 사람의 메시지만 보고 싶을 때.",
                        },
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": [],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        query = args.get("query", "")
        author = args.get("author")
        if not query and not author:
            return {"ok": False, "error": "query 또는 author 중 하나는 필요해"}
        date_from, date_to = _parse_kst_date_range(request.clean_content or "")

        # 검색 전 조용한 증분 갱신으로 최신 메시지·청크까지 포함
        await self._archive.ingest_channel(request.channel_id, notify=False)

        # 검색은 서버(guild) 전체 기록 대상
        limit = min(int(args.get("limit", 20)), 50)
        keyword_matches = await self._archive.search(
            request.guild_id,
            query,
            author,
            limit,
            before_message_id=request.message_id,
            exclude_mention_user_id=request.bot_user_id,
            date_from=date_from,
            date_to=date_to,
        )
        hybrid_matches = []
        hybrid_error = None
        if query:
            try:
                hybrid_matches = await self._archive.hybrid_search(
                    request.guild_id,
                    query,
                    limit=min(limit, 10),
                    candidate_limit=50,
                    author=author,
                    before_message_id=request.message_id,
                    exclude_mention_user_id=request.bot_user_id,
                    date_from=date_from,
                    date_to=date_to,
                )
            except Exception as e:
                hybrid_error = str(e)
                logger.warning(f"hybrid archive search failed: {e}")

        evidence_markdown = self._archive.build_search_evidence_markdown(
            keyword_matches,
            hybrid_matches,
            query=query,
            limit=3,
        )

        return {
            "ok": True,
            "keyword_matches": keyword_matches,
            "hybrid_matches": hybrid_matches,
            "evidence_markdown": evidence_markdown,
            "hybrid_error": hybrid_error,
            "author_filter": author,
            "date_filter_kst": {
                "from": date_from.isoformat() if date_from else None,
                "to": date_to.isoformat() if date_to else None,
            },
        }


class RecallThisDayTool(BaseTool):
    def __init__(self, archive_service: MessageArchiveService) -> None:
        self._archive = archive_service

    @property
    def name(self) -> str:
        return "recall_this_day"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "recall_this_day",
                "description": (
                    "오늘 날짜에 해당하는 과거(작년 이전) 대화를 하나 꺼내 "
                    "'N년 전 오늘' embed로 채널에 보여준다. 활발했던 대화만 자동 선별한다. "
                    "사용자가 'n년 전 오늘', '옛날 오늘 뭐했어', '그날 추억' 등을 물을 때 사용. "
                    "embed는 이 툴이 직접 전송하므로, 결과의 found가 true면 respond_text로는 "
                    "짧은 코멘트만 달아라(대화 내용을 다시 나열하지 마). "
                    "found가 false면 오늘 날짜엔 꺼낼 추억이 없다는 뜻이다."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        return await self._archive.recall_this_day(
            request.guild_id, request.channel_id
        )


class AnalyzeUserTool(BaseTool):
    def __init__(self, archive_service: MessageArchiveService) -> None:
        self._archive = archive_service

    @property
    def name(self) -> str:
        return "analyze_user"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "analyze_user",
                "description": (
                    "특정 사용자의 성격·성향을 분석할 때 사용한다. "
                    "그 사람이 직접 쓴 메시지를 전 기간에 걸쳐 대표 샘플(최신 50개 + 균등 250개)로 가져온다. "
                    "반환된 메시지들을 직접 읽고 말투·관심사·성격을 추론해서 답하라. "
                    "검색 전 기록이 자동 갱신되며 시간이 걸릴 수 있으니 say로 먼저 알려라."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "author": {
                            "type": "string",
                            "description": "분석할 사용자 이름(부분일치).",
                        },
                    },
                    "required": ["author"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        author = args.get("author")
        if not author:
            return {"ok": False, "error": "author가 필요해"}

        await self._archive.ingest_channel(request.channel_id, notify=False)
        messages = await self._archive.sample_user_messages(
            request.guild_id, author
        )
        if not messages:
            return {"ok": True, "count": 0, "messages": [], "note": "메시지 없음"}
        return {"ok": True, "count": len(messages), "messages": messages}
