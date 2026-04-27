#!/usr/bin/env python3
"""CLI CFO agent backed only by the Preconfin Agent API."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from typing import Any


BASE_URL = "https://api.preconfin.com/api"
EXECUTE_PATH = "/agent/tools/execute"
PROBLEM_STATUSES = {"failed", "error", "blocked", "pending", "warning", "review"}
QUESTION_ROUTE_MAP = (
    ("burn rate", "burn_rate", "get_people_snapshot"),
    ("top expenses", "top_expenses", "get_financial_state"),
    ("needs attention", "needs_attention", "get_financial_state"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query the Preconfin Agent API for CFO-style answers."
    )
    parser.add_argument("question", help='Question to ask, for example: "top expenses"')
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw JSON response returned by the API.",
    )
    output_group.add_argument(
        "--report",
        action="store_true",
        help="Print a markdown report instead of CLI text.",
    )
    return parser.parse_args()


def env_agent_key() -> str:
    agent_key = os.getenv("PRECONFIN_AGENT_KEY", "").strip()
    if not agent_key:
        raise RuntimeError("PRECONFIN_AGENT_KEY is required.")
    return agent_key


def call_agent(tool_name: str, arguments: dict[str, Any]) -> Any:
    agent_key = env_agent_key()
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "arguments": arguments,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{EXECUTE_PATH}",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {agent_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8").strip()
        message = detail or "No response body returned."
        raise RuntimeError(
            f"Preconfin API error while executing {tool_name}: {exc.code} {exc.reason}. {message}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach Preconfin API: {exc.reason}") from exc

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Preconfin API returned invalid JSON for {tool_name}: {raw_body[:200]}"
        ) from exc


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def display_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)):
        return payload["data"]
    return payload


def iter_nodes(payload: Any) -> Any:
    stack = [payload]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, dict):
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def cents_to_dollars(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) / 100.0
    return None


def to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def find_first_dict(payload: Any, candidate_keys: set[str]) -> dict[str, Any] | None:
    for node in iter_nodes(payload):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if normalize_text(key).lower() in candidate_keys and isinstance(value, dict):
                return value
    return None


def first_text(mapping: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        text = normalize_text(value)
        if text:
            return text
    return None


def first_number(mapping: dict[str, Any] | None, keys: tuple[str, ...]) -> float | None:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        number = to_float(value)
        if number is not None:
            return number
    return None


def format_currency(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def format_runway(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    if math.isinf(value):
        return "Cash-generating"
    return f"{value:.1f} months"


def detect_request(question: str) -> tuple[str, str]:
    lowered = normalize_text(question).lower()
    matches = [(intent, tool_name) for phrase, intent, tool_name in QUESTION_ROUTE_MAP if phrase in lowered]
    if not matches:
        supported = ", ".join(f'"{phrase}"' for phrase, _intent, _tool in QUESTION_ROUTE_MAP)
        raise RuntimeError(f"Unsupported question. Use one of: {supported}.")
    unique_matches = sorted(set(matches))
    if len(unique_matches) > 1:
        raise RuntimeError("Question is ambiguous. Ask for only one supported intent at a time.")
    return unique_matches[0]


def burn_metric_details(payload: Any) -> dict[str, Any]:
    root = display_payload(payload)
    burn = find_first_dict(root, {"burn_rate"})
    runway = find_first_dict(root, {"cash_runway", "runway"})
    runway_warning = find_first_dict(root, {"runway_warning"})

    if burn is None and isinstance(root, dict):
        burn = root
    if runway is None and isinstance(root, dict) and any(
        key in root for key in ("months", "runway_months", "unavailable_reason")
    ):
        runway = root

    burn_amount = None
    if isinstance(burn, dict):
        burn_amount = cents_to_dollars(burn.get("amount_cents"))
        if burn_amount is None:
            burn_amount = cents_to_dollars(burn.get("burn_rate_cents"))
        if burn_amount is None:
            burn_amount = first_number(burn, ("amount", "value"))

    runway_months = None
    runway_unavailable_reason = None
    if isinstance(runway, dict):
        runway_months = first_number(runway, ("months", "runway_months", "value"))
        runway_unavailable_reason = first_text(runway, ("unavailable_reason", "reason"))
    elif isinstance(root, dict):
        runway_months = first_number(root, ("runway_months",))

    window_start = None
    window_end = None
    if isinstance(burn, dict) and isinstance(burn.get("window"), dict):
        window_start = normalize_text(burn["window"].get("start")) or None
        window_end = normalize_text(burn["window"].get("end")) or None

    return {
        "burn_amount": burn_amount,
        "unavailable_reason": first_text(burn, ("unavailable_reason", "reason")),
        "as_of": first_text(burn, ("as_of", "captured_at", "fresh_as_of"))
        or first_text(root if isinstance(root, dict) else None, ("captured_at", "as_of", "fresh_as_of")),
        "window_start": window_start,
        "window_end": window_end,
        "runway_months": runway_months,
        "runway_unavailable_reason": runway_unavailable_reason,
        "runway_warning": runway_warning if isinstance(runway_warning, dict) else None,
    }


def financial_state_details(payload: Any) -> dict[str, Any]:
    root = display_payload(payload)
    if not isinstance(root, dict):
        return {
            "net_amount": None,
            "readiness_status": None,
            "readiness_summary": None,
            "period_start": None,
            "period_end": None,
        }

    net_state = root.get("net_state") if isinstance(root.get("net_state"), dict) else root
    readiness = root.get("readiness") if isinstance(root.get("readiness"), dict) else {}
    period = root.get("period") if isinstance(root.get("period"), dict) else {}

    net_amount = None
    if isinstance(net_state, dict):
        net_amount = first_number(net_state, ("net_amount", "amount", "net"))

    return {
        "net_amount": net_amount,
        "readiness_status": first_text(readiness, ("status",)),
        "readiness_summary": first_text(
            readiness,
            ("summary", "reason", "not_ready_reason"),
        ),
        "period_start": first_text(period, ("start",)),
        "period_end": first_text(period, ("end",)),
    }


def extract_attention_items(payload: Any, limit: int = 6) -> list[str]:
    root = display_payload(payload)
    items: list[str] = []
    seen: set[str] = set()

    details = financial_state_details(root)
    if details["net_amount"] is not None and details["net_amount"] < 0:
        message = f"Negative net: {format_currency(details['net_amount'])}"
        seen.add(message)
        items.append(message)

    burn_details = burn_metric_details(root)
    runway_warning = burn_details.get("runway_warning")
    if isinstance(runway_warning, dict):
        runway_text = " ".join(
            part
            for part in (
                first_text(runway_warning, ("title",)),
                first_text(runway_warning, ("reason",)),
                first_text(runway_warning, ("next_step",)),
            )
            if part
        )
        if runway_text:
            message = f"Cash runway warning: {runway_text}"
            if message not in seen:
                seen.add(message)
                items.append(message)
    elif burn_details["runway_months"] is not None:
        message = f"Cash runway: {format_runway(burn_details['runway_months'])}"
        if message not in seen:
            seen.add(message)
            items.append(message)
    elif burn_details["runway_unavailable_reason"]:
        message = f"Cash runway unavailable: {burn_details['runway_unavailable_reason']}"
        if message not in seen:
            seen.add(message)
            items.append(message)

    for node in iter_nodes(root):
        if not isinstance(node, dict):
            continue
        status = normalize_text(node.get("status")).lower()
        if status not in PROBLEM_STATUSES:
            continue
        context = first_text(node, ("title", "label", "name", "event_type", "action_type")) or "Item"
        detail = first_text(
            node,
            ("detail", "description", "summary", "reason", "message", "next_step", "approval_class_description"),
        )
        message = f"{context} ({status})"
        if detail:
            message = f"{message}: {detail}"
        if message not in seen:
            seen.add(message)
            items.append(message)
        if len(items) >= limit:
            break

    return items[:limit]


def candidate_expense_tables(payload: Any) -> list[tuple[int, list[dict[str, Any]]]]:
    root = display_payload(payload)
    label_keys = {"label", "name", "merchant", "category", "vendor", "description", "title", "pnl_bucket"}
    amount_keys = {"amount", "amount_cents", "spend", "spend_cents", "expenses", "expense", "total", "total_cents", "value"}
    key_bonus = {
        "top_expenses": 5,
        "expenses": 4,
        "rows": 3,
        "items": 2,
        "category": 2,
        "merchant": 2,
    }
    tables: list[tuple[int, list[dict[str, Any]]]] = []

    for node in iter_nodes(root):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
                continue
            score = key_bonus.get(normalize_text(key).lower(), 0)
            sample = value[:5]
            if any(any(field in item for field in label_keys) for item in sample):
                score += 3
            if any(any(field in item for field in amount_keys) for item in sample):
                score += 4
            if score > 0:
                tables.append((score, value))

    return sorted(tables, key=lambda item: item[0], reverse=True)


def amount_from_row(row: dict[str, Any]) -> float | None:
    for cents_key in ("amount_cents", "spend_cents", "total_cents"):
        amount = cents_to_dollars(row.get(cents_key))
        if amount is not None:
            return amount
    return first_number(row, ("amount", "spend", "expenses", "expense", "total", "value"))


def normalize_expense_rows(payload: Any) -> list[dict[str, str]]:
    tables = candidate_expense_tables(payload)
    if not tables:
        return []

    rows = tables[0][1]
    normalized_rows: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        label = (
            first_text(row, ("label", "name", "merchant", "category", "vendor", "description", "title", "pnl_bucket"))
            or f"Item {index}"
        )
        amount = format_currency(amount_from_row(row))
        txn_count = first_number(row, ("txn_count", "count"))
        percentage = first_number(row, ("pct_of_total", "pct_of_revenue", "share", "percent"))

        normalized = {
            "#": str(index),
            "Expense": label,
            "Amount": amount,
        }
        if txn_count is not None:
            normalized["Txns"] = str(int(txn_count)) if txn_count.is_integer() else f"{txn_count:.2f}"
        if percentage is not None:
            normalized["Pct"] = f"{percentage:.1f}%"
        normalized_rows.append(normalized)
    return normalized_rows


def format_text_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "No expense rows were returned by the API."

    columns = list(rows[0].keys())
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    separator = "  ".join("-" * widths[column] for column in columns)
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    body = "\n".join(
        "  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns)
        for row in rows
    )
    return "\n".join((header, separator, body))


def format_markdown_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "_No expense rows were returned by the API._"

    columns = list(rows[0].keys())
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _column in columns) + " |"
    body = "\n".join(
        "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |"
        for row in rows
    )
    return "\n".join((header, divider, body))


def render_cli(intent: str, tool_name: str, question: str, payload: Any) -> str:
    lines = [
        "Preconfin CFO Agent",
        f"Question: {question}",
        f"Tool: {tool_name}",
        f"Source: {BASE_URL}{EXECUTE_PATH}",
        "",
    ]

    if intent == "burn_rate":
        details = burn_metric_details(payload)
        lines.append("Burn Rate")
        if details["burn_amount"] is not None:
            lines.append(f"- Burn rate: {format_currency(details['burn_amount'])}/month")
        else:
            lines.append("- Burn rate: Unavailable")
        if details["window_start"] and details["window_end"]:
            lines.append(f"- Window: {details['window_start']} to {details['window_end']}")
        if details["as_of"]:
            lines.append(f"- As of: {details['as_of']}")
        if details["unavailable_reason"]:
            lines.append(f"- Note: {details['unavailable_reason']}")

        warnings = extract_attention_items(payload, limit=4)
        if warnings:
            lines.append("")
            lines.append("Warnings")
            lines.extend(f"- {item}" for item in warnings)
        return "\n".join(lines)

    if intent == "top_expenses":
        rows = normalize_expense_rows(payload)
        lines.append("Top Expenses")
        lines.append(format_text_table(rows))
        warnings = extract_attention_items(payload, limit=4)
        if warnings:
            lines.append("")
            lines.append("Warnings")
            lines.extend(f"- {item}" for item in warnings)
        return "\n".join(lines)

    details = financial_state_details(payload)
    lines.append("Needs Attention")
    if details["period_start"] and details["period_end"]:
        lines.append(f"- Period: {details['period_start']} to {details['period_end']}")
    if details["readiness_status"]:
        lines.append(f"- Readiness: {details['readiness_status']}")
    if details["readiness_summary"]:
        lines.append(f"- Summary: {details['readiness_summary']}")
    if details["net_amount"] is not None:
        lines.append(f"- Net: {format_currency(details['net_amount'])}")

    warnings = extract_attention_items(payload)
    if warnings:
        lines.append("")
        lines.append("Warnings")
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- No explicit warnings were found in the API response.")
    return "\n".join(lines)


def render_markdown(intent: str, tool_name: str, question: str, payload: Any) -> str:
    lines = [
        "# Preconfin CFO Agent Report",
        "",
        f"- Question: {question}",
        f"- Tool: {tool_name}",
        f"- Source: `{BASE_URL}{EXECUTE_PATH}`",
        "",
    ]

    if intent == "burn_rate":
        details = burn_metric_details(payload)
        lines.append("## Burn Rate")
        lines.append("")
        if details["burn_amount"] is not None:
            lines.append(f"- Burn rate: {format_currency(details['burn_amount'])}/month")
        else:
            lines.append("- Burn rate: Unavailable")
        if details["window_start"] and details["window_end"]:
            lines.append(f"- Window: {details['window_start']} to {details['window_end']}")
        if details["as_of"]:
            lines.append(f"- As of: {details['as_of']}")
        if details["unavailable_reason"]:
            lines.append(f"- Note: {details['unavailable_reason']}")

    elif intent == "top_expenses":
        rows = normalize_expense_rows(payload)
        lines.append("## Top Expenses")
        lines.append("")
        lines.append(format_markdown_table(rows))

    else:
        details = financial_state_details(payload)
        lines.append("## Needs Attention")
        lines.append("")
        if details["period_start"] and details["period_end"]:
            lines.append(f"- Period: {details['period_start']} to {details['period_end']}")
        if details["readiness_status"]:
            lines.append(f"- Readiness: {details['readiness_status']}")
        if details["readiness_summary"]:
            lines.append(f"- Summary: {details['readiness_summary']}")
        if details["net_amount"] is not None:
            lines.append(f"- Net: {format_currency(details['net_amount'])}")

    warnings = extract_attention_items(payload)
    lines.append("")
    lines.append("## Warnings")
    lines.append("")
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- No explicit warnings were found in the API response.")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    intent, tool_name = detect_request(args.question)
    payload = call_agent(tool_name, {})

    if args.raw:
        print(json.dumps(payload, indent=2))
        return 0

    if args.report:
        print(render_markdown(intent, tool_name, args.question, payload))
        return 0

    print(render_cli(intent, tool_name, args.question, payload))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
