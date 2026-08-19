from __future__ import annotations

import argparse

from .config import load_config
from .engine import ResearchEngine
from .messages import compare_result, compact_result, detail_result, history_message, hot_results, stats_message


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


if __name__ == "__main__":
    main()

