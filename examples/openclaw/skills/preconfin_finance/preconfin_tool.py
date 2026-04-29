#!/usr/bin/env python3
"""Zero-dependency Preconfin finance adapter for OpenClaw-compatible local use."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://api.preconfin.com/api"
EXECUTE_PATH = "/agent/tools/execute"
TIMEOUT_SECONDS = 30

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


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(word in lowered for word in SENSITIVE_KEYWORDS)


def execute_tool(base_url: str, agent_key: str, tool_name: str) -> Any:
    payload = json.dumps({"tool_name": tool_name, "arguments": {}}).encode("utf-8")
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


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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


def run_tools(tool_names: list[str], *, raw: bool) -> str:
    base_url, agent_key = load_env()
    blocks: list[str] = []
    heading_level = 3 if len(tool_names) > 1 else 2
    for tool_name in tool_names:
        payload = execute_tool(base_url, agent_key, tool_name)
        blocks.append(render_block(tool_name, payload, agent_key=agent_key, raw=raw, heading_level=heading_level))
    return "\n\n".join(blocks)


def run_question(question: str, *, raw: bool) -> str:
    return run_tools(route_query(question), raw=raw)


def build_report(*, raw: bool) -> str:
    base_url, agent_key = load_env()
    sections = ["# Preconfin Report", ""]
    for title, tool_names in REPORT_SECTIONS:
        sections.append(f"## {title}")
        sections.append("")
        for tool_name in tool_names:
            payload = execute_tool(base_url, agent_key, tool_name)
            sections.append(render_block(tool_name, payload, agent_key=agent_key, raw=raw, heading_level=3))
            sections.append("")
    return "\n".join(sections).rstrip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic local adapter for the Preconfin Agent API.",
    )
    parser.add_argument("question", nargs="*", help="finance question to route")
    parser.add_argument("--raw", action="store_true", help="print sanitized JSON")
    parser.add_argument("--report", action="store_true", help="print a multi-section finance report")
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
            output = build_report(raw=args.raw)
        else:
            output = run_question(question, raw=args.raw)
        print(output)
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
