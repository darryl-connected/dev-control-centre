"""Credential-free factory defaults and validation for one workspace policy."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any

VERSION = 1
ROLE_ORDER = ("coordinator", "writer", "reviewer")
ROUTES = {
    "coordinator": {"provider": "openai", "model": "gpt-6.1-sol", "reasoning": "high"},
    "writer": {"provider": "deepseek", "model": "deepseek-flash", "reasoning": "model-default"},
    "reviewer": {"provider": "openai", "model": "gpt-6.1-sol", "reasoning": "high"},
}
ATTEMPT_LIMITS = {
    "writer.initial": {"calls": 60, "minutes": 25},
    "writer.repair": {"calls": 30, "minutes": 15},
    "reviewer.initial": {"calls": 60, "minutes": 25},
    "reviewer.rereview": {"calls": 40, "minutes": 20},
}
REPAIR_LIMIT = 2
REASONING = {"model-default", "off", "minimal", "low", "medium", "high", "xhigh", "max"}
_PROVIDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
# Preserve case and namespaces. No glob, whitespace or empty path components.
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+@-]*(?:/[A-Za-z0-9][A-Za-z0-9_.:+@-]*)*")
_MAX_BYTES = 64 * 1024


def route_text(route: dict) -> str:
    return f"{route['provider']}/{route['model']}"


def parse_identity(value: object, field: str) -> tuple[str, str]:
    if isinstance(value, str) and len(value) <= 512:
        provider, _, model = value.partition("/")
        if _PROVIDER.fullmatch(provider) and _MODEL.fullmatch(model):
            return provider, model
    raise ValueError(f"{field}: expected an exact provider/model identity (no patterns or whitespace)")


def validate_route(value: object, field: str) -> None:
    if not isinstance(value, dict) or set(value) != {"provider", "model", "reasoning"}:
        raise ValueError(f"{field}: expected provider, model and reasoning")
    provider, model = value["provider"], value["model"]
    if not isinstance(provider, str) or not isinstance(model, str) or "/" in provider:
        raise ValueError(f"{field}: expected an exact provider and model")
    parse_identity(route_text(value), field)
    if not isinstance(value["reasoning"], str) or value["reasoning"] not in REASONING:
        raise ValueError(f"{field}.reasoning: expected one of {', '.join(sorted(REASONING))}")


def validate_routes(routes: object) -> None:
    if not isinstance(routes, dict) or set(routes) != set(ROLE_ORDER):
        raise ValueError("routes: expected coordinator, writer and reviewer")
    for role in ROLE_ORDER:
        validate_route(routes[role], f"routes.{role}")


def allowance(value: object, field: str) -> None:
    if not isinstance(value, dict) or set(value) != {"calls", "minutes"} or any(
        type(number) is not int or number <= 0 for number in value.values()
    ):
        raise ValueError(f"{field}: expected positive integer calls and minutes")


def effective_policy(value: dict) -> dict:
    if set(value) - {"version", "routes", "attempt_limits", "repair_limit"}:
        raise ValueError("policy: unknown fields; only version, routes, attempt_limits and repair_limit are allowed")
    if type(value.get("version")) is not int or value["version"] != VERSION:
        raise ValueError(f"policy.version: expected {VERSION}")
    routes = deepcopy(ROUTES)
    attempts = deepcopy(ATTEMPT_LIMITS)
    for key, defaults in (("routes", routes), ("attempt_limits", attempts)):
        overrides = value.get(key, {})
        if not isinstance(overrides, dict) or set(overrides) - set(defaults):
            raise ValueError(f"policy.{key}: expected only {', '.join(defaults)}")
        defaults.update(deepcopy(overrides))
    validate_routes(routes)
    for name, limit in attempts.items():
        allowance(limit, f"attempt_limits.{name}")
    repairs = value.get("repair_limit", REPAIR_LIMIT)
    if type(repairs) is not int or repairs < 0:
        raise ValueError("policy.repair_limit: expected a nonnegative integer")
    return {"version": VERSION, "routes": routes, "attempt_limits": attempts, "repair_limit": repairs}


def digest(selected: dict) -> str:
    return hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict:
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError(f"duplicate policy field: {key}")
        row[key] = value
    return row


def load(workspace: Path) -> tuple[dict, dict]:
    """Read just the declared local policy; never traverse a symlink or load other config."""
    path = workspace / ".dcc/policy.json"
    source: str | None = None
    source_sha: str | None = None
    raw = {"version": VERSION}
    try:
        if workspace.resolve(strict=True) != workspace or not workspace.is_dir():
            raise ValueError("policy workspace must be an existing physical directory")
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError("policy path must not use symlinks")
        try:
            item = path.lstat()
        except FileNotFoundError:
            item = None
        if item is not None:
            if not stat.S_ISREG(item.st_mode) or item.st_size > _MAX_BYTES:
                raise ValueError("expected a bounded regular policy file")
            data = path.read_bytes()
            if len(data) > _MAX_BYTES:
                raise ValueError("policy file exceeds the size limit")
            content = json.loads(data, object_pairs_hook=_unique)
            if not isinstance(content, dict):
                raise ValueError("expected a policy object")
            raw = content
            source, source_sha = str(path), hashlib.sha256(data).hexdigest()
        return effective_policy(raw), {"source": source, "sha256": source_sha}
    except (OSError, ValueError, RecursionError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
