import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 하트비트/HTTP 덤프 등 노이즈가 심한 서드파티 라이브러리
_NOISY_LOGGERS = [
    "discord.gateway",
    "discord.http",
    "discord.client",
    "discord.voice_client",
    "discord.player",
    "httpcore",
    "httpx",
    "openai._base_client",
]


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "sachikobot.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
