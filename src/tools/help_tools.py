from tools.base import BaseTool

# 봇이 빠뜨리지 않도록 주는 '기능 인벤토리'. 사용자에게 이걸 그대로 보여주는 게 아니라
# LLM이 자기 말투로 풀어서 안내하는 데 쓰는 참고 목록이다.
CAPABILITIES = [
    "대화: 멘션하면 대화. 최근 맥락 기억",
    "이미지 보기: 올린 이미지 보고 답함. 나중에 그 이미지 얘기도 기억",
    "채팅 기록: 너희 옛날 대화 검색·요약, 특정인 성향 분석",
    "기억: '기억해'/'잊어줘'로 정보 저장·삭제",
    "웹 검색: 날씨·뉴스·시세 같은 최신 정보 검색",
    "집계 질문: '가장 오래된 채팅', '말 많은 사람 순위' 등",
    "음악: 보이스 입장/퇴장, 노래 검색·재생·스킵·대기열 (여러 곡도)",
    "이미지 생성: '그려줘'로 그림 생성",
    "이미지 편집: 이미지 첨부 + '바꿔줘'로 변형",
    "N년 전 오늘: 그날의 재밌던 대화 소환 (매일 밤 9시 자동도)",
]


class ShowHelpTool(BaseTool):
    @property
    def name(self) -> str:
        return "show_help"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "show_help",
                "description": (
                    "사용자가 '뭐 할 수 있어', '도움말', '기능' 등을 물으면 호출한다. "
                    "봇의 전체 기능 목록(capabilities)을 받아서, 그걸 빠짐없이 다 언급하되 "
                    "딱딱하게 나열하지 말고 네 말투로 자연스럽게 풀어서 안내해라."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict, request) -> dict:
        return {"ok": True, "capabilities": CAPABILITIES}
