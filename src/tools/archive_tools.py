from services.message_archive_service import MessageArchiveService
from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)


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
                    "검색 결과의 source_url/context_sources는 원본 Discord 메시지 근거다. "
                    "과거 대화를 근거로 답할 때는 관련 source_url을 함께 제시해라. "
                    "query에는 핵심 키워드나 주제를 넣어라. "
                    "특정 사람에 대한 질문('A는 뭘 좋아해?', 'A가 한 말')이면 author에 그 사람 이름을 넣어라. "
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
        )
        hybrid_matches = []
        if query:
            hybrid_matches = await self._archive.hybrid_search(
                request.guild_id,
                query,
                limit=min(limit, 10),
                candidate_limit=50,
                author=author,
                before_message_id=request.message_id,
                exclude_mention_user_id=request.bot_user_id,
            )

        return {
            "ok": True,
            "keyword_matches": keyword_matches,
            "hybrid_matches": hybrid_matches,
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
