"""Shared environment loading helpers for the Python CFO demos."""

from __future__ import annotations

from pathlib import Path
import os


_ENV_LOADED = False
_ENV_FILES = (".env", ".env.local")


def _candidate_env_paths() -> list[Path]:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    examples_root = here.parents[2]
    return [
        examples_root / name
        for name in _ENV_FILES
    ] + [
        repo_root / name
        for name in _ENV_FILES
    ]


def load_local_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    for env_path in _candidate_env_paths():
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)

    _ENV_LOADED = True


def required_env(name: str) -> str:
    load_local_env()
    value = os.getenv(name, "").strip()
    if value:
        return value
    raise RuntimeError(
        f"{name} is required. Export it in your shell or add {name}=... to "
        "preconfin-agent-examples/.env or ./.env."
    )
