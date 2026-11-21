#!/usr/bin/env python3
"""Read one selected ClickUp task and bounded context. No task readiness verdict."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, NoReturn, Protocol

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from clickup_reader import Reader, ReadError, intake, result, selection


class TextWriter(Protocol):
    def write(self, text: str, /) -> object: ...


def safe_write(stream: TextWriter, text: str, token: str) -> bool:
    # Fail closed if an unusual credential overlaps JSON syntax/static output or
    # the literal bytes appear across an escape/replacement boundary.
    if token and token in text:
        return False
    stream.write(text)
    return True


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's default error can echo arbitrary supplied arguments.
        raise ReadError("invalid_selection")

    def _print_message(self, message: str | None, file: TextWriter | None = None) -> None:
        if message and not safe_write(file or sys.stderr, message, os.environ.get("CLICKUP_API_TOKEN", "")):
            raise ReadError("invalid_selection")


def sanitize(value: Any, token: str) -> Any:
    if not token:
        return value
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]")
    if isinstance(value, dict):
        return {key: sanitize(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, token) for item in value]
    return value


def main() -> int:
    token = os.environ.get("CLICKUP_API_TOKEN", "")
    parser = Parser(prog="clickup.py", description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="mode", required=True)
    read = sub.add_parser("read", help="read one selected task", allow_abbrev=False)
    read.add_argument("--task", required=True, help="native ID, supported task URL, or custom task ID")
    read.add_argument("--workspace-id", help="numeric ClickUp Workspace ID, for custom task IDs only")
    try:
        args = parser.parse_args()
        task_id, workspace = selection(args.task, args.workspace_id)
        context = intake(Reader(token), task_id, workspace)
    except ReadError as error:
        context = result(None, [], [error.detail(kind="selection")])
    try:
        if not safe_write(sys.stdout, json.dumps(sanitize(context, token), indent=2) + "\n", token):
            safe_write(sys.stderr, "Cannot safely render intake output with this credential.\n", token)
            return 2
    except (OSError, UnicodeError):
        return 2
    return {"observed": 0, "partial": 1, "blocked": 2}[context["status"]]


if __name__ == "__main__":
    sys.exit(main())
