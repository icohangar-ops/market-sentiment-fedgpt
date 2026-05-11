"""CLI for Market Sentiment FedGPT."""
from __future__ import annotations

import argparse
import sys

from market_sentiment_fedgpt.core import analyze_market, report_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-sentiment-fedgpt")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Analyze Fed tone, market sentiment, and portfolio risk.")
    analyze.add_argument("--indicators", required=True)
    analyze.add_argument("--speech", required=True)
    analyze.add_argument("--portfolio")
    analyze.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "analyze":
        report = analyze_market(args.indicators, args.speech, args.portfolio)
        sys.stdout.write((report_json(report) if args.json else report.to_markdown()) + "\n")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

