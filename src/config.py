import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
DATABASE_URL_RO: str = os.getenv("DATABASE_URL_RO", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# 'N년 전 오늘' 자동 포스팅 (0이면 비활성)
RECALL_CHANNEL_ID: int = int(os.getenv("RECALL_CHANNEL_ID", "0"))
RECALL_HOUR_KST: int = int(os.getenv("RECALL_HOUR_KST", "21"))

# 웹 검색 (Tavily) — 비어있으면 web_search 비활성
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
