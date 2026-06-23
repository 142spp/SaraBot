from services.affinity_service import AffinityService, affinity_band
from tools.base import BaseTool

MAX_DELTA = 10  # 한 번에 바꿀 수 있는 호감도 폭


class AdjustAffinityTool(BaseTool):
    def __init__(self, affinity_service: AffinityService) -> None:
        self._affinity = affinity_service

    @property
    def name(self) -> str:
        return "adjust_affinity"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "adjust_affinity",
                "description": (
                    "지금 말 건 사람에 대한 네 호감도를 조절한다. "
                    "상대가 눈에 띄게 잘해주거나 챙겨주면 올리고(+), "
                    "시비 걸거나 무례하거나 귀찮게 굴면 내려(-). "
                    "사소한 건 건드리지 말고 의미 있는 순간에만 써. "
                    "한 번에 -10~+10 범위, 호감도는 0~100으로 누적된다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "delta": {
                            "type": "integer",
                            "description": "변화량 (-10~+10). 양수=호감 상승, 음수=하락.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "왜 바꾸는지 짧게 (로그·맥락용).",
                        },
                    },
                    "required": ["delta"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        try:
            delta = int(args.get("delta", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "delta는 정수여야 해."}
        if delta == 0:
            return {"ok": False, "error": "delta가 0이면 바꿀 게 없어."}
        delta = max(-MAX_DELTA, min(MAX_DELTA, delta))

        new_score = await self._affinity.adjust(
            request.guild_id, request.user_id, delta
        )
        # 점수는 반환하지 않는다 — 봇이 숫자를 사용자에게 흘리지 못하게.
        return {"ok": True, "band": affinity_band(new_score)}
