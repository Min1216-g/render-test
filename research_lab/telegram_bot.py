from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .config import load_config
from .comparison import ComparisonLab
from .daily_comparison import DailyComparisonLab, cumulative_message, daily_result_message
from .engine import ResearchEngine
from .messages import (
    compare_result,
    compact_result,
    comparison_report_message,
    comparison_started_message,
    detail_result,
    existing_scanner_message,
    history_message,
    hot_results,
    research_lab_message,
    stats_message,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("research_lab.telegram")
TELEGRAM_MAX_LENGTH = 3900


class TelegramResearchBot:
    def __init__(self) -> None:
        self.config = load_config()
        if not self.config.telegram_ready:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        self.engine = ResearchEngine(self.config)
        self.comparison = ComparisonLab(self.config)
        self.daily = DailyComparisonLab(self.config)
        self.session = requests.Session()
        self.base_url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}"

    def run(self) -> None:
        offset = None
        LOG.info("Telegram Research Lab started. allowed_chat_id=%s", self.config.allowed_chat_id)
        while True:
            try:
                response = self.session.get(
                    f"{self.base_url}/getUpdates",
                    params={"timeout": self.config.poll_timeout, "offset": offset},
                    timeout=self.config.poll_timeout + 10,
                )
                response.raise_for_status()
                payload = response.json()
                for update in payload.get("result", []):
                    offset = max(offset or 0, update["update_id"] + 1)
                    self.handle_update(update)
            except requests.Timeout:
                LOG.warning("API_TIMEOUT: Telegram getUpdates timeout")
            except requests.HTTPError as exc:
                LOG.error("API_ERROR: Telegram HTTP %s", getattr(exc.response, "status_code", "unknown"))
                time.sleep(3)
            except Exception as exc:
                LOG.exception("RESEARCH_FAILED: %s", exc)
                time.sleep(3)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = str(message.get("text", "")).strip()
        if not chat_id or not text:
            return
        if chat_id != self.config.allowed_chat_id:
            self.send_message(chat_id, "ACCESS_DENIED")
            LOG.warning("ACCESS_DENIED chat_id=%s", chat_id)
            return
        self.send_message(chat_id, self.dispatch(text))

    def dispatch(self, text: str) -> str:
        try:
            parts = text.split()
            command = parts[0].lower()
            ticker = parts[1].upper() if len(parts) > 1 else ""
            if command in {"/start", "/help"}:
                return help_message()
            if command == "/hot":
                return hot_results(self.engine.hot())
            if command == "/comparison" and len(parts) > 1:
                action = parts[1].lower()
                if action == "start":
                    limit = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 40
                    return comparison_started_message([record.to_dict() for record in self.comparison.start(limit)])
                if action == "update":
                    return f"COMPARISON RETURNS UPDATED: {self.comparison.update_returns()}"
                if action == "report":
                    return comparison_report_message(self.comparison.report())
                if action == "sample":
                    limit = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 6
                    records = [record.to_dict() for record in self.comparison.start(limit, save=False)]
                    lines: list[str] = []
                    for record in records[:3]:
                        lines.append(existing_scanner_message(record))
                        lines.append("")
                        lines.append(research_lab_message(record))
                        lines.append("")
                    return "\n".join(lines).strip()
            if command == "/daily" and len(parts) > 1:
                action = parts[1].lower()
                if action == "run":
                    results = [result.to_dict() for result in self.daily.run_due(send_telegram=False)]
                    return "\n\n".join(daily_result_message(result) for result in results) or "NO_DAILY_RESULT_DUE"
                if action == "report" and len(parts) > 3:
                    market = parts[2].upper()
                    result = self.daily.calculate(market, parts[3])
                    return daily_result_message(result.to_dict()) if result else "NO_DAILY_RESULT_CREATED"
                if action == "cumulative":
                    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
                    return cumulative_message(self.daily.cumulative(days))
            if command == "/compare" and ticker:
                return compare_result(self.engine.research(ticker))
            if command == "/research" and ticker == "HISTORY":
                return history_message(self.engine.history())
            if command == "/research" and ticker == "STATS":
                changed = self.engine.update_paper_returns()
                stats = self.engine.stats()
                suffix = f"\n\nPaper returns updated: {changed}" if changed else ""
                return stats_message(stats) + suffix
            if command == "/research" and ticker == "DETAIL" and len(parts) > 2:
                return detail_result(self.engine.research(parts[2].upper()))
            if command == "/research" and ticker:
                return compact_result(self.engine.research(ticker))
            return "RESEARCH_FAILED: 지원 명령어는 /research TICKER, /compare TICKER, /hot, /research history, /research stats, /research detail TICKER 입니다."
        except FileNotFoundError as exc:
            return f"DATA_UNAVAILABLE: {exc}"
        except LookupError as exc:
            return str(exc)
        except requests.Timeout:
            return "API_TIMEOUT: Telegram 또는 외부 요청 시간이 초과되었습니다."
        except requests.HTTPError as exc:
            return f"API_ERROR: HTTP {getattr(exc.response, 'status_code', 'unknown')}"
        except Exception as exc:
            LOG.exception("RESEARCH_FAILED dispatch=%s", text)
            return f"RESEARCH_FAILED: {type(exc).__name__}"

    def send_message(self, chat_id: str, text: str) -> None:
        chunks = [text[i : i + TELEGRAM_MAX_LENGTH] for i in range(0, len(text), TELEGRAM_MAX_LENGTH)] or [""]
        for chunk in chunks:
            response = self.session.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()


def help_message() -> str:
    return "\n".join(
        [
            "Telegram Research Lab",
            "",
            "/research NVDA",
            "/compare NVDA",
            "/hot",
            "/research history",
            "/research stats",
            "/research detail NVDA",
            "/comparison start 40",
            "/comparison sample 6",
            "/comparison update",
            "/comparison report",
            "/daily run",
            "/daily cumulative 30",
        ]
    )


def main() -> None:
    TelegramResearchBot().run()


if __name__ == "__main__":
    main()
