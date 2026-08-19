from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
LAB_DIR = Path(__file__).resolve().parent
DATA_DIR = LAB_DIR / "data"
DEFAULT_MARKET_RESULTS = BASE_DIR / "market_scanner_results.csv"
DEFAULT_ALLOWED_CHAT_ID = "8749935590"


@dataclass(frozen=True)
class ResearchLabConfig:
    telegram_bot_token: str
    allowed_chat_id: str
    market_results_file: Path
    history_file: Path
    poll_timeout: int
    request_timeout: int
    hot_limit: int

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token)


def load_config() -> ResearchLabConfig:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return ResearchLabConfig(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        allowed_chat_id=os.getenv("RESEARCH_ALLOWED_CHAT_ID", DEFAULT_ALLOWED_CHAT_ID).strip(),
        market_results_file=Path(os.getenv("RESEARCH_MARKET_RESULTS_FILE", str(DEFAULT_MARKET_RESULTS))).expanduser(),
        history_file=Path(os.getenv("RESEARCH_HISTORY_FILE", str(DATA_DIR / "research_history.jsonl"))).expanduser(),
        poll_timeout=int(os.getenv("RESEARCH_TELEGRAM_POLL_TIMEOUT", "30")),
        request_timeout=int(os.getenv("RESEARCH_REQUEST_TIMEOUT", "20")),
        hot_limit=max(1, min(20, int(os.getenv("RESEARCH_HOT_LIMIT", "12")))),
    )

