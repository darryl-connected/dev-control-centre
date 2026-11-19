#!/usr/bin/env python3
"""
factory-job.py — Structured factory job manifest and gates.

A JSON manifest is the single source of truth. The brief is rendered from it,
so the contract cannot drift between a handwritten brief and the rules.

Commands:
    python scripts/factory-job.py example
    python scripts/factory-job.py snapshot MANIFEST > out.json   # save outside the target repo
    python scripts/factory-job.py render MANIFEST
    python scripts/factory-job.py preflight MANIFEST [--json]
    python scripts/factory-job.py candidate MANIFEST --candidate PATH
    python scripts/factory-job.py integration MANIFEST --candidate PATH --review RECEIPT [--json]

Exit codes: 0 pass, 1 rejected, 2 the check could not run.

This gate does not execute verification commands, run tests or authenticate a
reviewer. It checks structure, live baseline, allowed paths, hashes and the
explicit review attestation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import factory_contract as contract


def _print_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    for error in result.get("errors", []):
        print(f"FAIL  {error}")
    for warning in result.get("warnings", []):
        print(f"WARN  {warning}")
    for note in result.get("notes", []):
        print(f"NOTE  {note}")
    if "duration_ms" in result:
        print(f"TIME  {result['duration_ms']} ms gate wall clock")
    print(f"\n{'OK' if result['ok'] else 'FAIL'}  {result['command']}")
    if result.get("ok"):
        print("Limits: the gate does not replay tests; review evidence is attested, not independently verified.")


def _timed(result: dict, started: float) -> dict:
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


def _load_manifest(path: str) -> dict:
    return contract.read_json(path, "manifest")


def command_example(args: argparse.Namespace) -> int:
    print(json.dumps(contract.example_manifest(), indent=2))
    return 0


def command_snapshot(args: argparse.Namespace) -> int:
    data = contract.read_json(args.manifest, "manifest")
    errors, _warnings = contract.validate_manifest(data, require_baseline=False)
    if errors:
        for error in errors:
            print(f"FAIL  {error}", file=sys.stderr)
        print("error: fix the manifest before snapshotting; the baseline was not captured", file=sys.stderr)
        return 1
    data["base"] = contract.capture_baseline(data["repo"])
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def command_render(args: argparse.Namespace) -> int:
    data = _load_manifest(args.manifest)
    errors, warnings = contract.validate_manifest(data, require_baseline=True)
    if errors:
        for error in errors:
            print(f"FAIL  {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"WARN  {warning}", file=sys.stderr)
    print(contract.render_brief(data), end="")
    return 0


def command_preflight(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    data = _load_manifest(args.manifest)
    result = _timed(contract.preflight(data), started)
    _print_result(result, args.json)
    return 0 if result["ok"] else 1


def command_candidate(args: argparse.Namespace) -> int:
    data = _load_manifest(args.manifest)
    errors, warnings = contract.validate_manifest(data, require_baseline=True)
    if errors:
        _print_result(
            {"command": "candidate", "ok": False, "errors": errors, "warnings": warnings},
            args.json,
        )
        return 1
    files = contract.content_map(args.candidate)
    manifest_value = contract.manifest_digest(data)
    digest = contract.candidate_digest(manifest_value, files)
    payload = {
        "manifest_digest": manifest_value,
        "candidate_digest": digest,
        "candidate": str(contract.real_path(args.candidate)),
        "files": files,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def command_integration(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    data = _load_manifest(args.manifest)
    receipt = contract.read_json(args.review, "review receipt")
    result = _timed(contract.integration(data, args.candidate, receipt), started)
    _print_result(result, args.json)
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Structured factory job manifest and gates.")
    sub = parser.add_subparsers(dest="command", required=True)

    example = sub.add_parser("example", help="print a manifest skeleton")
    example.set_defaults(func=command_example)

    snapshot = sub.add_parser("snapshot", help="capture the live baseline and print the manifest")
    snapshot.add_argument("manifest")
    snapshot.set_defaults(func=command_snapshot)

    render = sub.add_parser("render", help="render the worker brief from the manifest")
    render.add_argument("manifest")
    render.set_defaults(func=command_render)

    preflight_parser = sub.add_parser("preflight", help="validate the manifest, the baseline and tooling alignment")
    preflight_parser.add_argument("manifest")
    preflight_parser.add_argument("--json", action="store_true")
    preflight_parser.set_defaults(func=command_preflight)

    candidate = sub.add_parser("candidate", help="print the candidate content map and digest for review")
    candidate.add_argument("manifest")
    candidate.add_argument("--candidate", required=True)
    candidate.add_argument("--json", action="store_true")
    candidate.set_defaults(func=command_candidate)

    integration = sub.add_parser("integration", help="check a reviewed candidate read-only")
    integration.add_argument("manifest")
    integration.add_argument("--candidate", required=True)
    integration.add_argument("--review", required=True)
    integration.add_argument("--json", action="store_true")
    integration.set_defaults(func=command_integration)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (contract.ContractError, OSError, ValueError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
