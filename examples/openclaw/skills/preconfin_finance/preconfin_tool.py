#!/usr/bin/env python3
"""Zero-dependency Preconfin finance adapter for OpenClaw-compatible local use."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://api.preconfin.com/api"
EXECUTE_PATH = "/agent/tools/execute"
TIMEOUT_SECONDS = 30
DEFAULT_ACTIVITY_LIMIT = 8
REPORT_FILENAME = "preconfin_cfo_report.md"
CHARTS_DIRNAME = "charts"
CONNECTED_SOURCE_STATUSES = {"connected", "ready", "seeding"}

ROUTE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "get_people_snapshot",
        (
            "burn",
            "runway",
            "cash",
            "balance",
            "mrr",
            "arr",
            "revenue",
            "forecast",
            "snapshot",
        ),
    ),
    (
        "get_financial_state",
        (
            "expense",
            "expenses",
            "spend",
            "vendor",
            "vendors",
            "merchant",
            "merchants",
            "category",
            "categories",
            "financial state",
        ),
    ),
    (
        "get_people_charts",
        ("chart", "charts", "trend", "trends", "monthly", "history"),
    ),
    (
        "get_system_activity",
        ("activity", "recent", "changed", "changes", "failure", "failures", "sync"),
    ),
    (
        "get_sources",
        ("source", "sources", "integration", "integrations", "stale", "connection", "connections"),
    ),
]

NEEDS_ATTENTION_TOOLS = [
    "get_sources",
    "get_system_activity",
    "get_people_snapshot",
]

REPORT_SECTIONS: list[tuple[str, list[str]]] = [
    ("Burn And Runway", ["get_people_snapshot"]),
    ("Financial State", ["get_financial_state"]),
    ("System Activity", ["get_system_activity"]),
    ("Sources", ["get_sources"]),
]

TOOL_TITLES = {
    "get_people_snapshot": "People Snapshot",
    "get_people_charts": "People Charts",
    "get_financial_state": "Financial State",
    "get_system_activity": "System Activity",
    "get_sources": "Sources",
}

SENSITIVE_KEYWORDS = ("authorization", "api_key", "agent_key", "token", "secret", "password")
REDACTED = "[REDACTED]"
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
CHART_SPECS = {
    "cashflow": {
        "filename": "cashflow.png",
        "title": "Cashflow",
        "x_keys": ("period", "month", "date"),
        "primary_series": (
            ("income", "Income"),
            ("expense", "Expense"),
            ("net", "Net"),
        ),
        "secondary_series": (),
    },
    "operating_performance": {
        "filename": "operating_performance.png",
        "title": "Operating Performance",
        "x_keys": ("month", "period", "date"),
        "primary_series": (
            ("revenue", "Revenue"),
            ("expenses", "Expenses"),
            ("net", "Net"),
        ),
        "secondary_series": (),
    },
    "recurring_revenue": {
        "filename": "recurring_revenue.png",
        "title": "Recurring Revenue",
        "x_keys": ("month", "period", "date"),
        "primary_series": (
            ("mrr_cents", "MRR"),
            ("arr_cents", "ARR"),
        ),
        "secondary_series": (
            ("active_subscribers", "Active Subscribers"),
        ),
    },
}


def load_env() -> tuple[str, str]:
    base_url = os.environ.get("PRECONFIN_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    agent_key = os.environ.get("PRECONFIN_AGENT_KEY", "")
    if not agent_key:
        raise RuntimeError("PRECONFIN_AGENT_KEY is required in the environment.")
    return base_url, agent_key


def route_query(question: str) -> list[str]:
    lowered = question.strip().lower()
    if not lowered:
        return ["get_people_snapshot"]
    if "needs attention" in lowered:
        return list(NEEDS_ATTENTION_TOOLS)
    for tool_name, keywords in ROUTE_RULES:
        if any(keyword in lowered for keyword in keywords):
            return [tool_name]
    return ["get_people_snapshot"]


def redact_text(text: str, agent_key: str) -> str:
    redacted = text
    if agent_key:
        redacted = redacted.replace(agent_key, REDACTED)
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", f"Bearer {REDACTED}", redacted)
    return redacted


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(word in lowered for word in SENSITIVE_KEYWORDS)


def execute_tool(base_url: str, agent_key: str, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
    payload = json.dumps({"tool_name": tool_name, "arguments": arguments or {}}).encode("utf-8")
    request = urllib.request.Request(
        base_url + EXECUTE_PATH,
        data=payload,
        headers={
            "Authorization": f"Bearer {agent_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace").strip()
        details = redact_text(details, agent_key)
        message = f"Preconfin API request failed with HTTP {exc.code}."
        if details:
            message = f"{message} Response body: {details}"
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach Preconfin API: {exc.reason}") from exc

    if not response_text.strip():
        return {}

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"response_text": redact_text(response_text, agent_key)}


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


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def cents_to_dollars(value: Any) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    return number / 100.0


def find_first_dict(payload: Any, candidate_keys: set[str]) -> dict[str, Any] | None:
    for node in iter_nodes(payload):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if normalize_text(key).lower() in candidate_keys and isinstance(value, dict):
                return value
    return None


def find_list_of_dicts(payload: Any, candidate_keys: set[str]) -> list[dict[str, Any]]:
    for node in iter_nodes(payload):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if normalize_text(key).lower() in candidate_keys and isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def first_text(mapping: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        text = normalize_text(mapping.get(key))
        if text:
            return text
    return None


def first_number(mapping: dict[str, Any] | None, keys: tuple[str, ...]) -> float | None:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        number = to_float(mapping.get(key))
        if number is not None:
            return number
    return None


def looks_like_money_key(key: str | None) -> bool:
    if not key:
        return False
    lowered = key.lower()
    if lowered.endswith("_cents") or lowered.endswith("_usd") or lowered.endswith("_dollars"):
        return True
    money_terms = (
        "amount",
        "cash",
        "balance",
        "burn",
        "spend",
        "expense",
        "revenue",
        "mrr",
        "arr",
        "profit",
        "loss",
        "income",
    )
    return any(term in lowered for term in money_terms)


def friendly_key(key: str) -> str:
    text = key.replace("_", " ").strip()
    if not text:
        return "Value"
    return text[:1].upper() + text[1:]


def format_money(amount: float) -> str:
    return f"${amount:,.2f}"


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


def format_scalar(key: str | None, value: Any) -> str:
    if value is None:
        return "not provided"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if key and key.endswith("_cents") and is_number(value):
        return format_money(float(value) / 100.0)
    if is_number(value) and looks_like_money_key(key):
        return format_money(float(value))
    if is_number(value):
        if isinstance(value, int):
            return str(value)
        return f"{value:,.2f}"
    return str(value)


def sanitize_payload(value: Any, *, agent_key: str, raw: bool) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if is_sensitive_key(key_text):
                continue
            sanitized[key_text] = sanitize_payload(child, agent_key=agent_key, raw=raw)
        return sanitized
    if isinstance(value, list):
        return [sanitize_payload(item, agent_key=agent_key, raw=raw) for item in value]
    if isinstance(value, str):
        text = redact_text(value, agent_key)
        return text if raw else UUID_PATTERN.sub(REDACTED, text)
    return value


def render_lines(value: Any, *, key: str | None = None, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}- {(friendly_key(key) + ': ') if key else ''}(empty)"]
        lines: list[str] = []
        for child_key, child_value in value.items():
            label = friendly_key(child_key)
            if isinstance(child_value, (dict, list)):
                lines.append(f"{prefix}- {label}:")
                lines.extend(render_lines(child_value, key=child_key, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {label}: {format_scalar(child_key, child_value)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}- {(friendly_key(key) + ': ') if key else ''}(none)"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}- Item:")
                lines.extend(render_lines(item, key=key, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {format_scalar(key, item)}")
        return lines
    label = f"{friendly_key(key)}: " if key else ""
    return [f"{prefix}- {label}{format_scalar(key, value)}"]


def render_block(tool_name: str, payload: Any, *, agent_key: str, raw: bool, heading_level: int) -> str:
    heading = "#" * max(1, heading_level)
    title = TOOL_TITLES.get(tool_name, tool_name.replace("_", " ").title())
    sanitized = sanitize_payload(payload, agent_key=agent_key, raw=raw)
    lines = [f"{heading} {title}", ""]
    if raw:
        lines.append(json.dumps(sanitized, indent=2, sort_keys=True))
    else:
        lines.extend(render_lines(sanitized))
    return "\n".join(lines).strip()


def people_snapshot_details(payload: Any) -> dict[str, Any]:
    root = display_payload(payload)
    people = find_first_dict(root, {"people_snapshot"}) or (root if isinstance(root, dict) else None)
    if not isinstance(people, dict):
        people = {}

    cash_balance = find_first_dict(people, {"cash_balance"})
    burn_rate = find_first_dict(people, {"burn_rate"})
    runway = find_first_dict(people, {"cash_runway", "runway"})
    subscribers = find_first_dict(people, {"active_subscribers"})
    runway_warning = find_first_dict(people, {"runway_warning"})

    cash_amount = cents_to_dollars(cash_balance.get("amount_cents")) if isinstance(cash_balance, dict) else None
    if cash_amount is None:
        cash_amount = first_number(cash_balance, ("amount", "value"))

    burn_amount = cents_to_dollars(burn_rate.get("amount_cents")) if isinstance(burn_rate, dict) else None
    if burn_amount is None:
        burn_amount = first_number(burn_rate, ("amount", "value"))

    runway_months = first_number(runway, ("months", "runway_months", "value"))
    active_subscribers = first_number(subscribers, ("count", "value", "active_subscribers"))
    as_of = (
        first_text(cash_balance, ("as_of", "captured_at"))
        or first_text(burn_rate, ("as_of", "captured_at"))
        or first_text(people, ("captured_at", "as_of"))
        or first_text(root if isinstance(root, dict) else None, ("captured_at", "as_of"))
    )

    return {
        "cash_balance": cash_amount,
        "burn_amount": burn_amount,
        "runway_months": runway_months,
        "active_subscribers": active_subscribers,
        "as_of": as_of,
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

    return {
        "net_amount": first_number(net_state, ("net_amount", "amount", "net")),
        "readiness_status": first_text(readiness, ("status",)),
        "readiness_summary": first_text(readiness, ("summary", "reason", "not_ready_reason")),
        "period_start": first_text(period, ("start",)),
        "period_end": first_text(period, ("end",)),
    }


def format_status_value(value: str | None) -> str:
    return value or "Unknown"


def format_count_value(value: float | None) -> str:
    if value is None:
        return "Unknown"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def system_status_details(financial_payload: Any, sources_payload: Any) -> dict[str, str]:
    financial_root = display_payload(financial_payload)
    financial_mapping = financial_root if isinstance(financial_root, dict) else None
    source_coverage = find_first_dict(financial_root, {"source_coverage"})
    freshness = find_first_dict(financial_root, {"freshness"})
    traceability = find_first_dict(financial_root, {"traceability"})

    connected_count = first_number(source_coverage, ("connected_count",))
    total_count = first_number(source_coverage, ("total_count",))
    if connected_count is None or total_count is None:
        sources = find_list_of_dicts(display_payload(sources_payload), {"sources", "items"})
        if sources:
            total_count = float(len(sources))
            connected_like_count = 0
            for source in sources:
                if source.get("connected") is True:
                    connected_like_count += 1
                    continue
                status_values = (
                    normalize_text(source.get("status")).lower(),
                    normalize_text(source.get("connection_status")).lower(),
                    normalize_text(source.get("ingest_status")).lower(),
                    normalize_text(source.get("sync_status")).lower(),
                    normalize_text(source.get("state")).lower(),
                )
                if any(status in CONNECTED_SOURCE_STATUSES for status in status_values if status):
                    connected_like_count += 1
            connected_count = float(connected_like_count)

    freshness_status = first_text(freshness, ("freshness_status",))
    traceability_status = first_text(traceability, ("traceability_status",))
    traceability_note = first_text(financial_mapping, ("not_ready_reason",)) or first_text(
        traceability,
        ("not_ready_reason",),
    )

    if connected_count is None or total_count is None:
        sources_connected = "Unknown"
    else:
        sources_connected = f"{format_count_value(connected_count)} / {format_count_value(total_count)}"

    return {
        "sources_connected": sources_connected,
        "data_freshness": format_status_value(freshness_status),
        "traceability": format_status_value(traceability_status),
        "traceability_note": format_status_value(traceability_note),
    }


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
        label = first_text(row, ("label", "name", "merchant", "category", "vendor", "description", "title", "pnl_bucket")) or f"Item {index}"
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


def runway_warning_summary(runway_warning: dict[str, Any] | None) -> str | None:
    summary = first_text(runway_warning, ("reason",)) or first_text(runway_warning, ("title",))
    if not summary:
        return None
    if summary.endswith((".", "!", "?")):
        return summary
    return f"{summary}."


def is_very_low_cash_balance(
    cash_balance: float | None,
    burn_amount: float | None,
    runway_months: float | None,
) -> bool:
    if cash_balance is None:
        return False
    if cash_balance <= 0:
        return True
    if burn_amount is not None and burn_amount > 0 and cash_balance < burn_amount:
        return True
    if runway_months is not None and runway_months < 1:
        return True
    return cash_balance < 1000


def action_item(problem: str, action: str) -> str:
    return f"{problem} → {action}"


def find_uncategorized_expense(top_expenses: list[dict[str, str]]) -> dict[str, str] | None:
    for row in top_expenses:
        label = normalize_text(row.get("Expense"))
        if "uncategorized expense" in label.lower():
            return row
    return None


def build_immediate_takeaway(
    snapshot: dict[str, Any],
    financial: dict[str, Any],
    top_expenses: list[dict[str, str]],
) -> str:
    urgent = is_very_low_cash_balance(
        snapshot["cash_balance"],
        snapshot["burn_amount"],
        snapshot["runway_months"],
    )
    low_runway = snapshot["runway_months"] is not None and snapshot["runway_months"] < 1

    if urgent or low_runway:
        risk_signals: list[str] = []
        if low_runway:
            risk_signals.append(f"runway is {format_runway(snapshot['runway_months'])}")
        if snapshot["cash_balance"] is not None and urgent:
            risk_signals.append(f"cash balance is {format_currency(snapshot['cash_balance'])}")
        summary = " and ".join(risk_signals) or "cash is critically tight"
        takeaway = f"Cash is critically tight: {summary}."
        if financial["net_amount"] is not None and financial["net_amount"] < 0:
            return (
                f"{takeaway} Net position is {format_currency(financial['net_amount'])}, "
                "so cut nonessential spend and lock a funding or collections plan this week."
            )
        return f"{takeaway} Cut nonessential spend and confirm near-term funding or collections this week."

    takeaway = f"Cash covers {format_runway(snapshot['runway_months'])} at the current burn rate."
    if financial["net_amount"] is not None and financial["net_amount"] < 0:
        return (
            f"{takeaway} Net position is {format_currency(financial['net_amount'])}, "
            "so focus this week on improving cash efficiency and tightening the largest expense lines."
        )
    if top_expenses:
        largest = top_expenses[0]
        return (
            f"{takeaway} The largest reported expense line is "
            f"{largest['Expense']} at {largest['Amount']}, so review it first."
        )
    return f"{takeaway} Keep pressure on spend discipline this week."


def build_weekly_priorities(
    snapshot: dict[str, Any],
    financial: dict[str, Any],
    top_expenses: list[dict[str, str]],
    *,
    limit: int = 5,
) -> list[str]:
    priorities: list[str] = []
    seen: set[str] = set()

    def add(message: str | None) -> None:
        if not message or message in seen or len(priorities) >= limit:
            return
        seen.add(message)
        priorities.append(message)

    low_runway = snapshot["runway_months"] is not None and snapshot["runway_months"] < 1
    urgent_cash = is_very_low_cash_balance(
        snapshot["cash_balance"],
        snapshot["burn_amount"],
        snapshot["runway_months"],
    )

    if low_runway:
        add(f"Cut or defer spend immediately to extend runway beyond {format_runway(snapshot['runway_months'])}.")
    if urgent_cash:
        add(f"Build a 7-day cash plan around the current {format_currency(snapshot['cash_balance'])} balance.")
    if financial["net_amount"] is not None and financial["net_amount"] < 0:
        add(f"Close the {format_currency(financial['net_amount'])} net gap by matching spend to confirmed cash in.")

    uncategorized = find_uncategorized_expense(top_expenses)
    if uncategorized:
        label = normalize_text(uncategorized.get("Expense")) or "Uncategorized Expense"
        amount = uncategorized.get("Amount", "Unavailable")
        add(f"Review the {amount} {label} line and recategorize or stop anything nonessential.")

    for row in top_expenses:
        label = normalize_text(row.get("Expense"))
        if not label or (uncategorized and row is uncategorized):
            continue
        amount = row.get("Amount", "Unavailable")
        add(f"Review {label} at {amount} and confirm it is required this month.")

    if len(priorities) < 3 and snapshot["burn_amount"] is not None:
        add(f"Recheck the current burn rate of {format_currency(snapshot['burn_amount'])}/month against next-month commitments.")
    if len(priorities) < 3 and snapshot["cash_balance"] is not None:
        add(f"Check every near-term payment against the current cash balance of {format_currency(snapshot['cash_balance'])}.")
    if not priorities:
        add("Monitor cash, net, and the largest expense lines for any new deterioration.")

    return priorities[:limit]


def render_recent_activity(payload: Any, limit: int = DEFAULT_ACTIVITY_LIMIT) -> list[str]:
    events = find_list_of_dicts(display_payload(payload), {"events", "items", "activity"})
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


def extract_attention_items(financial_payload: Any, limit: int = 6) -> list[str]:
    root = display_payload(financial_payload)
    items: list[str] = []
    seen: set[str] = set()
    financial = financial_state_details(financial_payload)

    if financial["net_amount"] is not None and financial["net_amount"] < 0:
        message = f"Negative net: {format_currency(financial['net_amount'])}"
        seen.add(message)
        items.append(message)

    snapshot = people_snapshot_details(financial_payload)
    if snapshot["runway_warning"]:
        runway_text = " ".join(
            part
            for part in (
                first_text(snapshot["runway_warning"], ("title",)),
                first_text(snapshot["runway_warning"], ("reason",)),
                first_text(snapshot["runway_warning"], ("next_step",)),
            )
            if part
        )
        if runway_text:
            message = f"Cash runway warning: {runway_text}"
            seen.add(message)
            items.append(message)

    for node in iter_nodes(root):
        if not isinstance(node, dict):
            continue
        status = normalize_text(node.get("status")).lower()
        if status not in {"failed", "error", "blocked", "pending", "warning", "review"}:
            continue
        context = first_text(node, ("title", "label", "name", "event_type", "action_type")) or "Item"
        detail = first_text(node, ("detail", "description", "summary", "reason", "message", "next_step", "approval_class_description"))
        message = f"{context} ({status})"
        if detail:
            message = f"{message}: {detail}"
        if message not in seen:
            seen.add(message)
            items.append(message)
        if len(items) >= limit:
            break

    return items[:limit]


def render_attention_items(financial_payload: Any, sources_payload: Any, system_activity_payload: Any, *, limit: int = 6) -> list[str]:
    items = extract_attention_items(financial_payload, limit=limit)
    seen = set(items)

    for source in find_list_of_dicts(display_payload(sources_payload), {"sources", "items"}):
        name = normalize_text(source.get("display_name") or source.get("name") or source.get("source")) or "Unknown source"
        connected = source.get("connected")
        health = normalize_text(source.get("health")).lower()
        ingest_status = normalize_text(source.get("ingest_status")).lower()

        if connected is False:
            message = f"{name}: connection is incomplete."
        elif health in {"blocked", "review", "warning", "unknown"}:
            message = f"{name}: health is {health}."
        elif ingest_status in {"failed", "error", "blocked", "warning", "pending"}:
            message = f"{name}: ingest status is {ingest_status}."
        else:
            continue

        if message not in seen:
            seen.add(message)
            items.append(message)
        if len(items) >= limit:
            return items[:limit]

    for event_line in render_recent_activity(system_activity_payload, limit=limit):
        if "warning" not in event_line.lower() and "(failed)" not in event_line.lower() and "(error)" not in event_line.lower():
            continue
        message = event_line[2:] if event_line.startswith("- ") else event_line
        if message not in seen:
            seen.add(message)
            items.append(message)
        if len(items) >= limit:
            break

    return items[:limit] or ["No explicit warnings were found in the API response."]


def build_report_attention_items(
    snapshot_payload: Any,
    financial_payload: Any,
    sources_payload: Any,
    system_activity_payload: Any,
    top_expenses: list[dict[str, str]],
    *,
    limit: int = 6,
) -> list[str]:
    snapshot = people_snapshot_details(snapshot_payload)
    financial = financial_state_details(financial_payload)
    items: list[str] = []
    seen: set[str] = set()

    def add(message: str | None) -> None:
        if not message or message in seen or len(items) >= limit:
            return
        seen.add(message)
        items.append(message)

    runway_warning = runway_warning_summary(snapshot["runway_warning"])
    if runway_warning:
        add(
            action_item(
                f"Critical runway: {runway_warning}",
                "Finalize a same-week cash preservation plan and confirm funding or collections timing.",
            )
        )

    if is_very_low_cash_balance(
        snapshot["cash_balance"],
        snapshot["burn_amount"],
        snapshot["runway_months"],
    ):
        add(
            action_item(
                f"Low cash balance: {format_currency(snapshot['cash_balance'])}",
                "Pause nonessential spend and verify the next 7 days of cash commitments.",
            )
        )

    if financial["net_amount"] is not None and financial["net_amount"] < 0:
        add(
            action_item(
                f"Negative net: {format_currency(financial['net_amount'])}",
                "Cut the fastest discretionary costs and match this week's outflows to confirmed cash in.",
            )
        )

    uncategorized = find_uncategorized_expense(top_expenses)
    if uncategorized:
        top_expense_label = normalize_text(uncategorized.get("Expense"))
        add(
            action_item(
                f"High uncategorized expense: {top_expense_label} at {uncategorized.get('Amount', 'Unavailable')}",
                "Review and recategorize this line so cost controls target the right bucket.",
            )
        )

    for source in find_list_of_dicts(display_payload(sources_payload), {"sources", "items"}):
        name = normalize_text(source.get("display_name") or source.get("name") or source.get("source")) or "Unknown source"
        connected = source.get("connected")
        health = normalize_text(source.get("health")).lower()
        ingest_status = normalize_text(source.get("ingest_status")).lower()

        if connected is False:
            add(action_item(f"{name}: connection is incomplete.", "Reconnect the source and rerun ingestion."))
        elif health in {"blocked", "review", "warning", "unknown"}:
            add(action_item(f"{name}: health is {health}.", "Resolve the source issue before relying on this data."))
        elif ingest_status in {"failed", "error", "blocked", "warning", "pending"}:
            add(action_item(f"{name}: ingest status is {ingest_status}.", "Rerun or repair the ingest so this report uses current data."))

        if len(items) >= limit:
            return items[:limit]

    for event_line in render_recent_activity(system_activity_payload, limit=limit):
        lower_line = event_line.lower()
        if "warning" not in lower_line and "(failed)" not in lower_line and "(error)" not in lower_line:
            continue
        message = event_line[2:] if event_line.startswith("- ") else event_line
        add(action_item(message, "Resolve the failed workflow and confirm the next successful run."))
        if len(items) >= limit:
            break

    return items[:limit] or [
        action_item(
            "No high-signal attention items were detected from the current read surfaces.",
            "Keep monitoring cash, net, and spend trends for changes.",
        )
    ]


def chart_payload_details(payload: Any) -> dict[str, Any]:
    root = display_payload(payload)
    if isinstance(root, dict) and isinstance(root.get("charts"), dict):
        return root["charts"]
    return {}


def chart_rows(payload: Any, chart_name: str) -> list[dict[str, Any]]:
    chart = chart_payload_details(payload).get(chart_name)
    if isinstance(chart, dict) and isinstance(chart.get("rows"), list):
        return [row for row in chart["rows"] if isinstance(row, dict)]
    return []


def chart_period_label(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[str]:
    labels: list[str] = []
    for index, row in enumerate(rows, start=1):
        label = ""
        for key in keys:
            label = normalize_text(row.get(key))
            if label:
                break
        labels.append(label or f"Point {index}")
    return labels


def chart_series_values(rows: list[dict[str, Any]], key: str) -> list[float | None]:
    values: list[float | None] = []
    for row in rows:
        number = to_float(row.get(key))
        if number is None:
            values.append(None)
            continue
        values.append(number / 100.0 if key.endswith("_cents") else number)
    return values


def generate_chart_images(payload: Any) -> tuple[list[str], str | None]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import ticker
        import matplotlib.pyplot as plt
    except ImportError:
        return [], "Install matplotlib to generate chart images."

    charts_dir = Path(CHARTS_DIRNAME)
    charts_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []
    plt.style.use("seaborn-v0_8-whitegrid")

    for chart_name, spec in CHART_SPECS.items():
        rows = chart_rows(payload, chart_name)
        labels = chart_period_label(rows, spec["x_keys"])
        figure, axis = plt.subplots(figsize=(10, 5))
        axis.set_title(spec["title"])
        axis.set_xlabel("Period")
        axis.set_ylabel("Amount (USD)")
        axis.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
        plotted = False

        for field, label in spec["primary_series"]:
            series_values = chart_series_values(rows, field)
            numeric_pairs = [(index, value) for index, value in enumerate(series_values) if value is not None]
            if not numeric_pairs:
                continue
            axis.plot(
                [pair[0] for pair in numeric_pairs],
                [pair[1] for pair in numeric_pairs],
                marker="o",
                linewidth=2,
                label=label,
            )
            plotted = True

        if spec["secondary_series"]:
            secondary_axis = axis.twinx()
            secondary_axis.set_ylabel("Subscribers")
            secondary_axis.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
            for field, label in spec["secondary_series"]:
                series_values = chart_series_values(rows, field)
                numeric_pairs = [(index, value) for index, value in enumerate(series_values) if value is not None]
                if not numeric_pairs:
                    continue
                secondary_axis.plot(
                    [pair[0] for pair in numeric_pairs],
                    [pair[1] for pair in numeric_pairs],
                    marker="o",
                    linestyle="--",
                    linewidth=2,
                    label=label,
                    color="#2f855a",
                )
                plotted = True
            secondary_handles, secondary_labels = secondary_axis.get_legend_handles_labels()
        else:
            secondary_handles, secondary_labels = [], []

        if labels:
            axis.set_xticks(list(range(len(labels))))
            axis.set_xticklabels(labels, rotation=45, ha="right")

        primary_handles, primary_labels = axis.get_legend_handles_labels()
        if primary_handles or secondary_handles:
            axis.legend(primary_handles + secondary_handles, primary_labels + secondary_labels, loc="best")
        if not plotted:
            axis.text(0.5, 0.5, "No chart data returned.", ha="center", va="center", transform=axis.transAxes)

        figure.tight_layout()
        output_path = charts_dir / spec["filename"]
        figure.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(figure)
        generated.append(output_path.as_posix())

    return generated, None


def build_report_markdown(
    snapshot_payload: Any,
    financial_payload: Any,
    system_activity_payload: Any,
    sources_payload: Any,
    charts_payload: Any,
    chart_paths: list[str],
) -> str:
    snapshot = people_snapshot_details(snapshot_payload)
    financial = financial_state_details(financial_payload)
    system_status = system_status_details(financial_payload, sources_payload)
    top_expenses = normalize_expense_rows(financial_payload)[:5]
    recent_activity = render_recent_activity(system_activity_payload)
    attention_items = build_report_attention_items(
        snapshot_payload,
        financial_payload,
        sources_payload,
        system_activity_payload,
        top_expenses,
    )
    weekly_priorities = build_weekly_priorities(snapshot, financial, top_expenses)
    immediate_takeaway = build_immediate_takeaway(snapshot, financial, top_expenses)

    lines = [
        "# Preconfin CFO Report",
        "",
        "## 🔴 Immediate Takeaway",
        "",
        f"- {immediate_takeaway}",
        "",
        "## Executive Summary",
        "",
        f"- Cash balance: {format_currency(snapshot['cash_balance'])}",
        f"- Burn rate: {format_currency(snapshot['burn_amount'])}/month" if snapshot["burn_amount"] is not None else "- Burn rate: Unavailable",
        f"- Runway: {format_runway(snapshot['runway_months'])}",
        f"- Net position: {format_currency(financial['net_amount'])}",
        f"- Readiness: {financial['readiness_status'] or 'Unavailable'}",
    ]

    if top_expenses:
        lines.append(f"- Largest reported expense line: {top_expenses[0]['Expense']} at {top_expenses[0]['Amount']}")
    if snapshot["runway_warning"]:
        warning = " ".join(
            part
            for part in (
                first_text(snapshot["runway_warning"], ("title",)),
                first_text(snapshot["runway_warning"], ("reason",)),
            )
            if part
        )
        if warning:
            lines.append(f"- Runway warning: {warning}")

    lines.extend(
        [
            "",
            "## Cash / Burn / Runway Snapshot",
            "",
            f"- Cash balance: {format_currency(snapshot['cash_balance'])}",
            f"- Burn rate: {format_currency(snapshot['burn_amount'])}/month" if snapshot["burn_amount"] is not None else "- Burn rate: Unavailable",
            f"- Runway: {format_runway(snapshot['runway_months'])}",
            f"- Active subscribers: {int(snapshot['active_subscribers']):,}" if snapshot["active_subscribers"] is not None else "- Active subscribers: Unavailable",
            f"- As of: {snapshot['as_of'] or 'Unavailable'}",
            "",
            "## System Status",
            "",
            f"- Sources connected: {system_status['sources_connected']}",
            f"- Data freshness: {system_status['data_freshness']}",
            f"- Traceability: {system_status['traceability']}",
            f"- Traceability note: {system_status['traceability_note']}",
            "",
            "## Top Expenses",
            "",
            format_markdown_table(top_expenses),
            "",
            "## Recent Activity",
            "",
        ]
    )
    lines.extend(recent_activity)
    lines.extend(["", "## Needs Attention", ""])
    lines.extend(f"- {item}" for item in attention_items)
    lines.extend(["", "## This Week’s Priorities", ""])
    lines.extend(f"- {item}" for item in weekly_priorities)
    lines.extend(["", "## Charts", ""])
    for chart_path in chart_paths:
        label = Path(chart_path).stem.replace("_", " ").title()
        lines.append(f"- [{label}]({chart_path})")
        lines.append(f"![{label}]({chart_path})")

    return "\n".join(lines).rstrip() + "\n"


def write_report_file(markdown: str) -> str:
    output_path = Path(REPORT_FILENAME)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path.as_posix()


def build_report(*, raw: bool, charts: bool) -> tuple[str, str, list[str], str | None]:
    del raw
    base_url, agent_key = load_env()
    snapshot_payload = execute_tool(base_url, agent_key, "get_people_snapshot")
    financial_payload = execute_tool(base_url, agent_key, "get_financial_state")
    system_activity_payload = execute_tool(base_url, agent_key, "get_system_activity", {"limit": DEFAULT_ACTIVITY_LIMIT})
    sources_payload = execute_tool(base_url, agent_key, "get_sources")
    charts_payload = execute_tool(base_url, agent_key, "get_people_charts", {"granularity": "month"})
    chart_paths, chart_message = generate_chart_images(charts_payload) if charts else ([], None)
    markdown = build_report_markdown(
        snapshot_payload,
        financial_payload,
        system_activity_payload,
        sources_payload,
        charts_payload,
        chart_paths,
    )
    report_path = write_report_file(markdown)
    return markdown, report_path, chart_paths, chart_message


def run_tools(tool_names: list[str], *, raw: bool) -> str:
    base_url, agent_key = load_env()
    blocks: list[str] = []
    heading_level = 3 if len(tool_names) > 1 else 2
    for tool_name in tool_names:
        payload = execute_tool(base_url, agent_key, tool_name)
        blocks.append(render_block(tool_name, payload, agent_key=agent_key, raw=raw, heading_level=heading_level))
    return "\n\n".join(blocks)


def run_question(question: str, *, raw: bool, charts: bool) -> tuple[str, list[str], str | None]:
    base_url, agent_key = load_env()
    tool_names = route_query(question)
    blocks: list[str] = []
    heading_level = 3 if len(tool_names) > 1 else 2
    charts_payload: Any | None = None

    for tool_name in tool_names:
        arguments = {"granularity": "month"} if tool_name == "get_people_charts" else {}
        payload = execute_tool(base_url, agent_key, tool_name, arguments)
        blocks.append(render_block(tool_name, payload, agent_key=agent_key, raw=raw, heading_level=heading_level))
        if tool_name == "get_people_charts":
            charts_payload = payload

    chart_paths: list[str] = []
    chart_message: str | None = None
    if charts:
        if charts_payload is None:
            charts_payload = execute_tool(base_url, agent_key, "get_people_charts", {"granularity": "month"})
        chart_paths, chart_message = generate_chart_images(charts_payload)

    return "\n\n".join(blocks), chart_paths, chart_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic local adapter for the Preconfin Agent API.",
    )
    parser.add_argument("question", nargs="*", help="finance question to route")
    parser.add_argument("--raw", action="store_true", help="print sanitized JSON")
    parser.add_argument("--report", action="store_true", help=f"generate {REPORT_FILENAME}; includes charts automatically")
    parser.add_argument("--charts", action="store_true", help=f"generate chart PNGs in {CHARTS_DIRNAME}/")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip()

    if args.report and question:
        parser.error("use either a question or --report, not both")
    if not args.report and not question:
        parser.error("a finance question is required unless --report is set")

    try:
        if args.report:
            output, report_path, chart_paths, chart_message = build_report(raw=args.raw, charts=True)
            print(output)
            print(f"Saved report to {report_path}.")
            if chart_message:
                print(chart_message)
            elif chart_paths:
                print("Generated charts:")
                for chart_path in chart_paths:
                    print(f"- {chart_path}")
        else:
            output, chart_paths, chart_message = run_question(question, raw=args.raw, charts=args.charts)
            print(output)
            if args.raw:
                if chart_message:
                    print(chart_message, file=sys.stderr)
                elif chart_paths:
                    print("Generated charts:", file=sys.stderr)
                    for chart_path in chart_paths:
                        print(f"- {chart_path}", file=sys.stderr)
            else:
                if chart_message:
                    print(chart_message)
                elif chart_paths:
                    print("Charts:")
                    for chart_path in chart_paths:
                        print(f"- {chart_path}")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
