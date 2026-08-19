from __future__ import annotations

import argparse

from .config import load_config
from .comparison import ComparisonLab, dump_json
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent Telegram Research Lab CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    research = sub.add_parser("research")
    research.add_argument("ticker")
    compare = sub.add_parser("compare")
    compare.add_argument("ticker")
    detail = sub.add_parser("detail")
    detail.add_argument("ticker")
    hot = sub.add_parser("hot")
    hot.add_argument("--limit", type=int, default=None)
    history = sub.add_parser("history")
    history.add_argument("--ticker", default=None)
    history.add_argument("--limit", type=int, default=10)
    sub.add_parser("stats")
    sub.add_parser("paper-update")
    comparison = sub.add_parser("comparison")
    comparison.add_argument("action", choices=["start", "update", "report", "history", "sample"])
    comparison.add_argument("--limit", type=int, default=40)
    comparison.add_argument("--json", action="store_true")
    daily = sub.add_parser("daily")
    daily.add_argument("action", choices=["due", "run", "calculate", "cumulative"])
    daily.add_argument("--market", choices=["KOREA", "US"], default=None)
    daily.add_argument("--date", default=None)
    daily.add_argument("--days", type=int, default=30)
    daily.add_argument("--send-telegram", action="store_true")
    daily.add_argument("--json", action="store_true")
    args = parser.parse_args()

    engine = ResearchEngine(load_config())
    if args.command == "research":
        print(compact_result(engine.research(args.ticker)))
    elif args.command == "compare":
        print(compare_result(engine.research(args.ticker)))
    elif args.command == "detail":
        print(detail_result(engine.research(args.ticker)))
    elif args.command == "hot":
        print(hot_results(engine.hot(args.limit)))
    elif args.command == "history":
        print(history_message(engine.history(args.limit, args.ticker)))
    elif args.command == "stats":
        changed = engine.update_paper_returns()
        print(stats_message(engine.stats()))
        print(f"\nPaper returns updated: {changed}")
    elif args.command == "paper-update":
        print(f"updated={engine.update_paper_returns()}")
    elif args.command == "comparison":
        lab = ComparisonLab(load_config())
        if args.action == "start":
            records = [record.to_dict() for record in lab.start(args.limit)]
            print(dump_json(records) if args.json else comparison_started_message(records))
        elif args.action == "update":
            print(f"updated={lab.update_returns()}")
        elif args.action == "report":
            report = lab.report()
            print(dump_json(report) if args.json else comparison_report_message(report))
        elif args.action == "history":
            records = lab.history(args.limit)
            print(dump_json(records) if args.json else comparison_started_message(records))
        elif args.action == "sample":
            records = [record.to_dict() for record in lab.start(args.limit, save=False)]
            if args.json:
                print(dump_json(records))
            else:
                print(comparison_started_message(records))
    elif args.command == "daily":
        lab = DailyComparisonLab(load_config())
        if args.action == "due":
            data = [{"market": market, "date": market_date.isoformat()} for market, market_date in lab.due_markets()]
            print(dump_json(data) if args.json else "\n".join(f"{item['market']} {item['date']}" for item in data))
        elif args.action == "run":
            results = [result.to_dict() for result in lab.run_due(send_telegram=args.send_telegram)]
            print(dump_json(results) if args.json else "\n\n".join(daily_result_message(result) for result in results) or "NO_DAILY_RESULT_DUE")
        elif args.action == "calculate":
            if not args.market or not args.date:
                raise SystemExit("daily calculate requires --market and --date")
            result = lab.calculate(args.market, args.date)
            if result is None:
                print("NO_DAILY_RESULT_CREATED")
            else:
                data = result.to_dict()
                print(dump_json(data) if args.json else daily_result_message(data))
        elif args.action == "cumulative":
            result = lab.cumulative(args.days)
            print(dump_json(result) if args.json else cumulative_message(result))


if __name__ == "__main__":
    main()
