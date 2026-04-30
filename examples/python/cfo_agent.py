#!/usr/bin/env python3
"""Deterministic CFO agent example for the Preconfin Agent API.

Usage:
  export PRECONFIN_BASE_URL="https://api.preconfin.com/api"
  export PRECONFIN_AGENT_KEY="your_agent_key_here"
  python3 examples/python/cfo_agent.py
  python3 examples/python/cfo_agent.py "what is my burn rate"
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from _env import load_local_env, required_env


DEFAULT_BASE_URL = "https://api.preconfin.com/api"
DEFAULT_ACTIVITY_LIMIT = 8
PROBLEM_STATUSES = {"failed", "error", "blocked", "warning", "pending"}
SOURCE_PROBLEM_HEALTH = {"blocked", "review", "warning", "unknown"}
REQUIRED_TOOLS = ("get_people_snapshot", "get_financial_state", "get_system_activity", "get_sources")


def env_base_url() -> str:
    load_local_env()
    return os.getenv("PRECONFIN_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def env_agent_key() -> str:
    return required_env("PRECONFIN_AGENT_KEY")


def api_request(base_url: str, agent_key: str, path: str, body: dict[str, Any] | None = None) -> Any:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=payload,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {agent_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"{exc.code} {exc.reason}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach Preconfin API: {exc.reason}") from exc


def walk_find_first_number(payload: Any, candidate_keys: set[str]) -> float | None:
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if str(key).strip().lower() in candidate_keys and isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return None


def find_list_of_dicts(payload: Any, candidate_keys: set[str]) -> list[dict[str, Any]]:
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                normalized = str(key).strip().lower()
                if normalized in candidate_keys and isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return []


def iso_window(days: int) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(days - 1, 0))
    return start.isoformat(), today.isoformat()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def format_currency(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def format_runway(months: float | None) -> str:
    if months is None:
        return "Unavailable"
    if math.isinf(months):
        return "Cash-generating"
    return f"{months:.1f} months"


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def runway_warning_summary(runway_warning: dict[str, Any] | None) -> str | None:
    if not isinstance(runway_warning, dict):
        return None
    summary = normalize_text(runway_warning.get("reason")) or normalize_text(runway_warning.get("title"))
    if not summary:
        return None
    if summary.endswith((".", "!", "?")):
        return summary
    return f"{summary}."


def amount_cents_to_dollars(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) / 100.0
    return None


def render_financial_summary(financial_state: dict[str, Any], people_snapshot_payload: dict[str, Any]) -> list[str]:
    net = walk_find_first_number(financial_state, {"net", "net_cash_flow", "net_cash", "net_amount"})
    people_snapshot = people_snapshot_payload.get("people_snapshot") if isinstance(people_snapshot_payload, dict) else {}
    if not isinstance(people_snapshot, dict):
        people_snapshot = {}

    cash_balance = amount_cents_to_dollars((people_snapshot.get("cash_balance") or {}).get("amount_cents"))
    burn = amount_cents_to_dollars((people_snapshot.get("burn_rate") or {}).get("amount_cents"))
    runway = (people_snapshot.get("cash_runway") or {}).get("months")
    active_subscribers = (people_snapshot.get("active_subscribers") or {}).get("count")
    runway_warning = people_snapshot.get("runway_warning")

    readiness = "Unavailable"
    readiness_payload = financial_state.get("readiness")
    if isinstance(readiness_payload, dict):
        readiness = normalize_text(readiness_payload.get("status")) or readiness

    as_of = (
        normalize_text(people_snapshot_payload.get("captured_at"))
        or normalize_text((people_snapshot.get("cash_balance") or {}).get("as_of"))
        or normalize_text(financial_state.get("as_of"))
        or normalize_text(financial_state.get("generated_at"))
        or "Unavailable"
    )

    summary = [
        f"- Cash Balance: {format_currency(cash_balance)}",
        f"- Burn: {format_currency(burn)} / month" if burn is not None else "- Burn: Unavailable",
        f"- Runway: {format_runway(runway)}",
        f"- Active Subscribers: {int(active_subscribers):,}"
        if isinstance(active_subscribers, (int, float))
        else "- Active Subscribers: Unavailable",
        f"- Net: {format_currency(net)}",
        f"- Readiness: {readiness}",
        f"- As of: {as_of}",
    ]

    warning_text = runway_warning_summary(runway_warning if isinstance(runway_warning, dict) else None)
    if warning_text:
        summary.append(f"- Warning: {warning_text}")

    return summary


def render_recent_activity(system_activity: dict[str, Any], limit: int) -> list[str]:
    events = find_list_of_dicts(system_activity, {"events", "items", "activity"})
    if not events:
        return ["- No recent activity returned by get_system_activity."]

    lines: list[str] = []
    for event in events[:limit]:
        timestamp = normalize_text(event.get("timestamp") or event.get("created_at") or event.get("occurred_at")) or "unknown time"
        title = normalize_text(event.get("title") or event.get("event_name") or event.get("name")) or "Untitled event"
        status = normalize_text(event.get("status")) or "unknown"
        detail = normalize_text(event.get("message") or event.get("description") or event.get("summary")) or "No details returned."
        lines.append(f"- [{timestamp}] {title} ({status}): {detail}")
    return lines


def render_attention_items(sources_payload: dict[str, Any], system_activity: dict[str, Any]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    for source in find_list_of_dicts(sources_payload, {"sources", "items"}):
        name = normalize_text(source.get("display_name") or source.get("name") or source.get("source")) or "Unknown source"
        connected = source.get("connected")
        health = normalize_text(source.get("health")).lower()
        ingest_status = normalize_text(source.get("ingest_status")).lower()

        if connected is False:
            message = f"- {name}: connection is incomplete."
        elif health in SOURCE_PROBLEM_HEALTH:
            message = f"- {name}: health is {health}."
        elif ingest_status in PROBLEM_STATUSES:
            message = f"- {name}: ingest status is {ingest_status}."
        else:
            continue

        if message not in seen:
            seen.add(message)
            items.append(message)

    for event in find_list_of_dicts(system_activity, {"events", "items", "activity"}):
        status = normalize_text(event.get("status")).lower()
        if status not in PROBLEM_STATUSES:
            continue
        detail = normalize_text(event.get("message") or event.get("description") or event.get("summary"))
        if not detail:
            continue
        message = f"- Activity warning: {detail}"
        if message not in seen:
            seen.add(message)
            items.append(message)
        if len(items) >= 6:
            break

    if not items:
        return ["- No high-signal attention items were detected from the current read surfaces."]
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a deterministic CFO briefing through the Preconfin Agent API.")
    parser.add_argument(
        "question",
        nargs="?",
        help='Optional question shortcut, for example: "what is my burn rate".',
    )
    parser.add_argument("--base-url", default=env_base_url(), help="Defaults to PRECONFIN_BASE_URL.")
    parser.add_argument("--days", type=int, default=90, help="Financial lookback window in days.")
    parser.add_argument("--activity-limit", type=int, default=DEFAULT_ACTIVITY_LIMIT, help="Maximum recent events to print.")
    parser.add_argument(
        "--mode",
        choices=("briefing", "financial-state", "recent-changes", "needs-attention"),
        default="briefing",
        help="Choose a narrower output mode.",
    )
    parser.add_argument(
        "--charts",
        action="store_true",
        help="Generate chart PNGs in charts/ using get_people_charts.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate preconfin_cfo_report.md and include charts automatically.",
    )
    return parser.parse_args()


def get_required_tools(base_url: str, agent_key: str) -> None:
    payload = api_request(base_url, agent_key, "/agent/tools")
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected /agent/tools response shape.")

    names = {str(item.get("name") or "").strip() for item in payload if isinstance(item, dict)}
    missing = [name for name in REQUIRED_TOOLS if name not in names]
    if missing:
        raise RuntimeError(f"Required tools are missing from /agent/tools: {', '.join(missing)}")


def execute_tool(base_url: str, agent_key: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = api_request(
        base_url,
        agent_key,
        "/agent/tools/execute",
        {
            "tool_name": tool_name,
            "arguments": arguments,
        },
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected /agent/tools/execute response for {tool_name}.")
    return payload


def main() -> int:
    args = parse_args()
    agent_key = env_agent_key()
    base_url = args.base_url.rstrip("/")

    get_required_tools(base_url, agent_key)

    if args.report and args.question:
        raise RuntimeError("Use either a question or --report, not both.")

    if args.question:
        import codex_cfo_agent as question_demo

        question_demo.BASE_URL = base_url
        charts_requested = args.charts or args.report
        if args.report:
            markdown, report_path, chart_paths, chart_message = question_demo.build_report_bundle(include_charts=True)
            print(markdown)
            print(f"Saved report to {report_path}.")
            if chart_message:
                print(chart_message)
            elif chart_paths:
                print("Generated charts:")
                for chart_path in chart_paths:
                    print(f"- {chart_path}")
            return 0
        intent, tool_name = question_demo.detect_request(args.question)
        payload = execute_tool(base_url, agent_key, tool_name, {})
        print(question_demo.render_cli(intent, tool_name, args.question, payload))
        if charts_requested:
            charts_payload = execute_tool(base_url, agent_key, "get_people_charts", {"granularity": "month"})
            chart_paths, chart_message = question_demo.generate_chart_images(charts_payload)
            print("")
            if chart_message:
                print(chart_message)
            else:
                print("Charts")
                for chart_path in chart_paths:
                    print(f"- {chart_path}")
        return 0

    start, end = iso_window(args.days)
    people_snapshot = execute_tool(
        base_url,
        agent_key,
        "get_people_snapshot",
        {},
    )
    financial_state = execute_tool(
        base_url,
        agent_key,
        "get_financial_state",
        {"start": start, "end": end, "exclude_transfers": True},
    )
    system_activity = execute_tool(
        base_url,
        agent_key,
        "get_system_activity",
        {"limit": args.activity_limit},
    )
    sources = execute_tool(base_url, agent_key, "get_sources", {})
    charts_requested = args.charts or args.report
    chart_paths: list[str] = []
    chart_message: str | None = None
    if charts_requested:
        charts_payload = execute_tool(
            base_url,
            agent_key,
            "get_people_charts",
            {"granularity": "month"},
        )
        import codex_cfo_agent as report_demo

        report_demo.BASE_URL = base_url
        chart_paths, chart_message = report_demo.generate_chart_images(charts_payload)

    if args.report:
        import codex_cfo_agent as report_demo

        report_demo.BASE_URL = base_url
        markdown = report_demo.build_report_markdown(
            people_snapshot,
            financial_state,
            system_activity,
            sources,
            charts_payload,
            chart_paths,
        )
        report_path = report_demo.write_report_file(markdown)
        print(markdown)
        print(f"Saved report to {report_path}.")
        if chart_message:
            print(chart_message)
        elif chart_paths:
            print("Generated charts:")
            for chart_path in chart_paths:
                print(f"- {chart_path}")
        return 0

    if args.mode == "financial-state":
        print(json.dumps(financial_state, indent=2))
        return 0
    if args.mode == "recent-changes":
        print("\n".join(render_recent_activity(system_activity, args.activity_limit)))
        return 0
    if args.mode == "needs-attention":
        print("\n".join(render_attention_items(sources, system_activity)))
        return 0

    print("Preconfin CFO Agent Briefing")
    print(f"Base URL: {base_url}")
    print(f"Generated: {utc_timestamp()}")
    print("")
    print("Financial Summary:")
    print("\n".join(render_financial_summary(financial_state, people_snapshot)))
    print("")
    print("Recent Activity:")
    print("\n".join(render_recent_activity(system_activity, args.activity_limit)))
    print("")
    print("Attention Needed:")
    print("\n".join(render_attention_items(sources, system_activity)))
    if chart_message:
        print("")
        print(chart_message)
    elif chart_paths:
        print("")
        print("Charts:")
        for chart_path in chart_paths:
            print(f"- {chart_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
