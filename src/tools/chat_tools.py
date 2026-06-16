from tools.base import BaseTool


class RespondTextTool(BaseTool):
    @property
    def name(self) -> str:
        return "respond_text"

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "respond_text",
                "description": "사용자에게 일반 텍스트로 답변한다. 항상 마지막에 호출한다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"}
                    },
                    "required": ["message"],
                },
            },
        }

    async def execute(self, args: dict, request) -> dict:
        return {"ok": True, "message": args["message"]}
