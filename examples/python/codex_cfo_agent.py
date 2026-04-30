#!/usr/bin/env python3
"""CLI CFO agent backed only by the Preconfin Agent API."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from typing import Any

from _env import required_env


BASE_URL = "https://api.preconfin.com/api"
EXECUTE_PATH = "/agent/tools/execute"
DEFAULT_ACTIVITY_LIMIT = 8
REPORT_FILENAME = "preconfin_cfo_report.md"
CHARTS_DIRNAME = "charts"
PROBLEM_STATUSES = {"failed", "error", "blocked", "pending", "warning", "review"}
SOURCE_PROBLEM_HEALTH = {"blocked", "review", "warning", "unknown"}
QUESTION_ROUTE_MAP = (
    ("burn rate", "burn_rate", "get_people_snapshot"),
    ("top expenses", "top_expenses", "get_financial_state"),
    ("needs attention", "needs_attention", "get_financial_state"),
)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query the Preconfin Agent API for CFO-style answers."
    )
    parser.add_argument("question", nargs="*", help='Question to ask, for example: "top expenses"')
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw JSON response returned by the API.",
    )
    output_group.add_argument(
        "--report",
        action="store_true",
        help=f"Generate {REPORT_FILENAME}. Includes charts automatically.",
    )
    parser.add_argument(
        "--charts",
        action="store_true",
        help=f"Generate chart PNGs in {CHARTS_DIRNAME}/ using get_people_charts.",
    )
    return parser.parse_args()


def env_agent_key() -> str:
    return required_env("PRECONFIN_AGENT_KEY")


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


def find_list_of_dicts(payload: Any, candidate_keys: set[str]) -> list[dict[str, Any]]:
    for node in iter_nodes(payload):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if normalize_text(key).lower() in candidate_keys and isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


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


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(word in lowered for word in SENSITIVE_KEYWORDS)


def friendly_key(key: str) -> str:
    text = key.replace("_", " ").strip()
    if not text:
        return "Value"
    return text[:1].upper() + text[1:]


def sanitize_snapshot_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if is_sensitive_key(key_text):
                continue
            sanitized[key_text] = sanitize_snapshot_payload(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_snapshot_payload(item) for item in value]
    if isinstance(value, str):
        return UUID_PATTERN.sub(REDACTED, value)
    return value


def format_snapshot_scalar(key: str | None, value: Any) -> str:
    if value is None:
        return "not provided"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if key and key.endswith("_cents") and isinstance(value, (int, float)):
        return format_currency(float(value) / 100.0)
    if isinstance(value, (int, float)):
        money_keys = ("amount", "cash", "balance", "burn", "revenue", "mrr", "arr", "expense")
        if key and any(term in key.lower() for term in money_keys):
            return format_currency(float(value))
        if isinstance(value, int):
            return str(value)
        return f"{value:,.2f}"
    return str(value)


def render_snapshot_lines(value: Any, *, key: str | None = None, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}- {(friendly_key(key) + ': ') if key else ''}(empty)"]
        lines: list[str] = []
        for child_key, child_value in value.items():
            label = friendly_key(child_key)
            if isinstance(child_value, (dict, list)):
                lines.append(f"{prefix}- {label}:")
                lines.extend(render_snapshot_lines(child_value, key=child_key, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {label}: {format_snapshot_scalar(child_key, child_value)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}- {(friendly_key(key) + ': ') if key else ''}(none)"]
        lines: list[str] = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}- Item:")
                lines.extend(render_snapshot_lines(item, key=key, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {format_snapshot_scalar(key, item)}")
        return lines
    label = f"{friendly_key(key)}: " if key else ""
    return [f"{prefix}- {label}{format_snapshot_scalar(key, value)}"]


def render_people_snapshot(payload: Any) -> str:
    snapshot = sanitize_snapshot_payload(display_payload(payload))
    lines = ["## People Snapshot", ""]
    lines.extend(render_snapshot_lines(snapshot))
    return "\n".join(lines)


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


def amount_from_row(row: dict[str, Any]) -> float | None:
    for cents_key in ("amount_cents", "spend_cents", "total_cents"):
        amount = cents_to_dollars(row.get(cents_key))
        if amount is not None:
            return amount
    return first_number(row, ("amount", "spend", "expenses", "expense", "total", "value"))


def outflow_breakdown_details(payload: Any) -> dict[str, Any]:
    root = display_payload(payload)
    if isinstance(root, dict):
        evidence = root.get("evidence")
        if isinstance(evidence, dict) and isinstance(evidence.get("outflow_breakdown"), dict):
            return evidence["outflow_breakdown"]
    found = find_first_dict(root, {"outflow_breakdown"})
    return found if isinstance(found, dict) else {}


def list_of_dict_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("rows", "items", "data", "values"):
            rows = value.get(key)
            if isinstance(rows, list):
                normalized_rows = [item for item in rows if isinstance(item, dict)]
                if normalized_rows:
                    return normalized_rows
    return []


def named_breakdown_rows(breakdown: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        rows = list_of_dict_rows(breakdown.get(key))
        if rows:
            return rows

    for node in iter_nodes(breakdown):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if normalize_text(key).lower() not in keys:
                continue
            rows = list_of_dict_rows(value)
            if rows:
                return rows
    return []


def normalize_outflow_rows(
    rows: list[dict[str, Any]],
    *,
    label_keys: tuple[str, ...],
    default_label: str,
) -> list[dict[str, str]]:
    normalized_entries: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        amount_value = amount_from_row(row)
        label = first_text(row, label_keys) or f"{default_label} {index}"
        txn_count = first_number(row, ("txn_count", "count"))
        percentage = first_number(row, ("pct_of_total", "pct_of_revenue", "share", "percent"))
        normalized_entries.append(
            {
                "label": label,
                "amount_value": amount_value,
                "amount": format_currency(amount_value),
                "txn_count": txn_count,
                "percentage": percentage,
            }
        )

    nonzero_entries = [
        entry for entry in normalized_entries if entry["amount_value"] is not None and entry["amount_value"] != 0
    ]
    display_entries = nonzero_entries if nonzero_entries else normalized_entries
    display_entries = sorted(
        display_entries,
        key=lambda entry: abs(entry["amount_value"]) if entry["amount_value"] is not None else -1,
        reverse=True,
    )

    formatted_rows: list[dict[str, str]] = []
    for index, entry in enumerate(display_entries, start=1):
        normalized = {
            "#": str(index),
            "Expense": entry["label"],
            "Amount": entry["amount"],
        }
        txn_count = entry["txn_count"]
        if txn_count is not None:
            normalized["Txns"] = str(int(txn_count)) if txn_count.is_integer() else f"{txn_count:.2f}"
        percentage = entry["percentage"]
        if percentage is not None:
            normalized["Pct"] = f"{percentage:.1f}%"
        formatted_rows.append(normalized)
    return formatted_rows


def expense_section_details(payload: Any) -> tuple[str, list[dict[str, str]]]:
    outflow_breakdown = outflow_breakdown_details(payload)
    category_rows = named_breakdown_rows(outflow_breakdown, ("category", "categories"))
    if category_rows:
        return (
            "Top Expenses",
            normalize_outflow_rows(
                category_rows,
                label_keys=("category", "label", "name", "description", "title", "pnl_bucket"),
                default_label="Category",
            ),
        )

    merchant_rows = named_breakdown_rows(outflow_breakdown, ("merchant", "merchants"))
    if merchant_rows:
        return (
            "Top Expense Merchants",
            normalize_outflow_rows(
                merchant_rows,
                label_keys=("merchant", "vendor", "label", "name", "description", "title"),
                default_label="Merchant",
            ),
        )

    return "Top Expenses", []


def runway_warning_summary(runway_warning: dict[str, Any] | None) -> str | None:
    summary = first_text(runway_warning, ("reason",)) or first_text(runway_warning, ("title",))
    if not summary:
        return None
    if summary.endswith((".", "!", "?")):
        return summary
    return f"{summary}."


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


def render_attention_items(
    financial_payload: Any,
    sources_payload: Any,
    system_activity_payload: Any,
    *,
    limit: int = 6,
) -> list[str]:
    items = extract_attention_items(financial_payload, limit=limit)
    seen = set(items)

    for source in find_list_of_dicts(display_payload(sources_payload), {"sources", "items"}):
        name = normalize_text(source.get("display_name") or source.get("name") or source.get("source")) or "Unknown source"
        connected = source.get("connected")
        health = normalize_text(source.get("health")).lower()
        ingest_status = normalize_text(source.get("ingest_status")).lower()

        if connected is False:
            message = f"{name}: connection is incomplete."
        elif health in SOURCE_PROBLEM_HEALTH:
            message = f"{name}: health is {health}."
        elif ingest_status in PROBLEM_STATUSES:
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


def chart_payload_details(payload: Any) -> dict[str, Any]:
    root = display_payload(payload)
    if isinstance(root, dict):
        charts = root.get("charts")
        if isinstance(charts, dict):
            return charts
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
        if key.endswith("_cents"):
            values.append(number / 100.0)
        else:
            values.append(number)
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
    expense_section_heading, normalized_expenses = expense_section_details(financial_payload)
    top_expenses = normalized_expenses[:5]
    recent_activity = render_recent_activity(system_activity_payload)
    attention_items = render_attention_items(financial_payload, sources_payload, system_activity_payload)

    lines = [
        "# Preconfin CFO Report",
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
        warning = runway_warning_summary(snapshot["runway_warning"])
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
            f"- Active subscribers: {int(snapshot['active_subscribers']):,}"
            if snapshot["active_subscribers"] is not None
            else "- Active subscribers: Unavailable",
            f"- As of: {snapshot['as_of'] or 'Unavailable'}",
            "",
            f"## {expense_section_heading}",
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


def build_report_bundle(*, include_charts: bool) -> tuple[str, str, list[str], str | None]:
    snapshot_payload = call_agent("get_people_snapshot", {})
    financial_payload = call_agent("get_financial_state", {})
    system_activity_payload = call_agent("get_system_activity", {"limit": DEFAULT_ACTIVITY_LIMIT})
    sources_payload = call_agent("get_sources", {})
    charts_payload = call_agent("get_people_charts", {"granularity": "month"})
    chart_paths, chart_message = generate_chart_images(charts_payload) if include_charts else ([], None)
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
    if intent == "burn_rate":
        return render_people_snapshot(payload)

    lines = [
        "Preconfin CFO Agent",
        f"Question: {question}",
        f"Tool: {tool_name}",
        f"Source: {BASE_URL}{EXECUTE_PATH}",
        "",
    ]

    if intent == "top_expenses":
        heading, rows = expense_section_details(payload)
        lines.append(heading)
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
        heading, rows = expense_section_details(payload)
        lines.append(f"## {heading}")
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
    question = " ".join(args.question).strip()
    charts_requested = args.charts or args.report

    if args.report and question:
        raise RuntimeError("Use either a question or --report, not both.")
    if not args.report and not question:
        raise RuntimeError('A question is required unless --report is used.')

    if args.report:
        markdown, report_path, chart_paths, chart_message = build_report_bundle(include_charts=True)
        print(markdown)
        print(f"Saved report to {report_path}.")
        if chart_message:
            print(chart_message)
        elif chart_paths:
            print("Generated charts:")
            for chart_path in chart_paths:
                print(f"- {chart_path}")
        return 0

    intent, tool_name = detect_request(question)
    payload = call_agent(tool_name, {})
    chart_paths: list[str] = []
    chart_message: str | None = None
    if charts_requested:
        charts_payload = call_agent("get_people_charts", {"granularity": "month"})
        chart_paths, chart_message = generate_chart_images(charts_payload)

    if args.raw:
        print(json.dumps(payload, indent=2))
        if chart_message:
            print(chart_message, file=sys.stderr)
        elif chart_paths:
            print("Generated charts:", file=sys.stderr)
            for chart_path in chart_paths:
                print(f"- {chart_path}", file=sys.stderr)
        return 0

    print(render_cli(intent, tool_name, question, payload))
    if chart_message:
        print("")
        print(chart_message)
    elif chart_paths:
        print("")
        print("Charts")
        for chart_path in chart_paths:
            print(f"- {chart_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
