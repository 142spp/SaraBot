from datetime import date, datetime

import config
from storage.db import get_ro_pool
from tools.base import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)

ROW_CAP = 100  # 결과 최대 행 수

SCHEMA_DOC = (
    "읽기 전용으로 채팅 기록 DB(PostgreSQL)에 SELECT 쿼리를 실행한다. "
    "키워드/의미 검색이 아닌 집계·정렬·시간 질문에 사용해라 "
    "(가장 오래된/최근 메시지, 말 많은 사람 순위, 특정 연도 대화, 카운트 등).\n"
    "테이블:\n"
    "messages(message_id, channel_id, guild_id, author_id, author_name, content, is_bot, created_at)\n"
    "message_chunks(id, channel_id, guild_id, start_msg_id, end_msg_id, start_at, end_at, authors, content, embedding)\n"
    "규칙:\n"
    "- 반드시 SELECT만. INSERT/UPDATE/DELETE/DROP 불가(차단됨).\n"
    "- 항상 현재 서버로 한정: WHERE guild_id = <이 서버 guild_id>.\n"
    "- author_name은 디스코드 닉네임(실명 아님). 실명은 메모리의 '디스코드 사용자 식별'로 닉 변환 후 사용.\n"
    "- created_at/start_at은 UTC TIMESTAMPTZ. 한국시간은 (col AT TIME ZONE 'Asia/Seoul').\n"
    "- message_chunks에서 embedding 컬럼은 절대 SELECT 하지 마(너무 큼). 컬럼을 명시적으로 골라라.\n"
    "- 최대 100행만 반환된다. 큰 결과는 집계하거나 LIMIT을 써라."
)


def _json_safe(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


class RunSqlTool(BaseTool):
    @property
    def name(self) -> str:
        return "run_sql"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "run_sql",
                "description": SCHEMA_DOC,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "실행할 SELECT 쿼리 (단일 문장, 세미콜론 생략 가능)",
                        }
                    },
                    "required": ["sql"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        if not config.DATABASE_URL_RO:
            return {"ok": False, "error": "SQL 기능 비활성(읽기 전용 접속 미설정)"}

        sql = (args.get("sql") or "").strip().rstrip(";").strip()
        if not sql:
            return {"ok": False, "error": "sql이 비어있어"}

        # 서브쿼리로 감싸 행 수를 강제 제한 + 구조적으로 SELECT만 허용
        wrapped = f"SELECT * FROM (\n{sql}\n) AS _sub LIMIT {ROW_CAP}"
        logger.info(f"run_sql | {sql[:200]}")

        try:
            pool = await get_ro_pool()
            async with pool.acquire() as conn:
                async with conn.transaction(readonly=True):
                    await conn.execute("SET LOCAL statement_timeout = '5s'")
                    rows = await conn.fetch(wrapped)
        except Exception as e:
            logger.warning(f"run_sql error: {e}")
            return {"ok": False, "error": f"쿼리 오류: {e}"}

        result = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]
        return {
            "ok": True,
            "row_count": len(result),
            "rows": result,
            "capped": len(result) >= ROW_CAP,
        }
