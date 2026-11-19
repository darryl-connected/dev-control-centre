#!/usr/bin/env python3
"""
validate-brief.py — ADVISORY check for historical Markdown factory briefs.

New factory jobs do not use a handwritten brief. They start from a JSON
manifest and are gated by `scripts/factory-job.py` (preflight and integration),
with tooling alignment via `scripts/factory-alignment.py`. This script is only
for checking historical Markdown.

It is not the authorising gate and cannot approve a job.

Checks every legacy field for a non-empty value, the authorisation lines, the
base commit, the budget limits and unfilled placeholders. The base commit is
format-checked only unless --repo is given, in which case it must resolve.

Exit codes:
- 0: the brief passes as an advisory check (warnings allowed unless --strict)
- 1: a field is missing or empty, or an authorisation line is absent
- 2: the check could not run (missing file, unreadable input, bad arguments)

Usage:
    python scripts/validate-brief.py /tmp/brief-task.md
    python scripts/validate-brief.py /tmp/brief-task.md --repo /absolute/path/to/repo
    python scripts/validate-brief.py /tmp/brief-task.md --strict --json
    python scripts/validate-brief.py --example
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import factory_contract as contract


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Advisory check for legacy Markdown factory briefs. Structured jobs use factory-job.py.",
    )
    parser.add_argument("brief", nargs="?", help="path to the legacy brief markdown file")
    parser.add_argument("--repo", help="repository used to verify the base commit exists")
    parser.add_argument("--example", action="store_true", help="print the legacy template and exit")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args()

    if args.example:
        print(contract.TEMPLATE_BRIEF, end="")
        return 0
    if not args.brief:
        parser.print_usage(sys.stderr)
        print("error: a brief path is required, or --example", file=sys.stderr)
        return 2

    path = Path(args.brief)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as failure:
        print(f"error: cannot read {path}: {failure}", file=sys.stderr)
        return 2

    errors, warnings = contract.check_markdown_brief(text, repo=args.repo)
    failed = bool(errors) or (args.strict and bool(warnings))

    if args.json:
        print(
            json.dumps(
                {
                    "brief": str(path),
                    "ok": not failed,
                    "advisory": True,
                    "errors": errors,
                    "warnings": warnings,
                    "strict": args.strict,
                },
                indent=2,
            )
        )
        return 1 if failed else 0

    for error in errors:
        print(f"FAIL  {error}")
    for warning in warnings:
        print(f"WARN  {warning}")
    status = "FAIL" if failed else "ADVISORY OK"
    print(f"\n{status}  {path}  ({len(errors)} error(s), {len(warnings)} warning(s))")
    print("This is not the authorising gate. Structured jobs use scripts/factory-job.py.")
    if failed:
        print("Fix the legacy brief, or print the template with --example.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
