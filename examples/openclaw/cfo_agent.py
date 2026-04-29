#!/usr/bin/env python3
"""Standalone CFO agent demo backed only by Preconfin."""

from __future__ import annotations

import argparse
import sys

from skills.preconfin_finance.preconfin_tool import build_report, run_question


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal CFO agent demo. Preconfin is the only financial source of truth.",
    )
    parser.add_argument("question", nargs="*", help="CFO question, for example: what is my burn rate")
    parser.add_argument("--report", action="store_true", help="generate a markdown CFO demo report")
    parser.add_argument("--raw", action="store_true", help="print raw JSON response for debugging")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip()
    if args.report and question:
        parser.error("--report does not accept a question")
    if not args.report and not question:
        parser.error("a CFO question is required unless --report is used")

    try:
        if args.report:
            sys.stdout.write(build_report())
            return 0
        sys.stdout.write(run_question(question, raw=args.raw))
        if not question.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
