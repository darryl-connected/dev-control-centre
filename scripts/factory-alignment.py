#!/usr/bin/env python3
"""
factory-alignment.py — Check that factory rules, tools and tests stay aligned.

Checks structure (rule IDs, gate references, generated brief, deterministic
probes) and whether the reviewed-source fingerprints have changed. It never
updates a fingerprint and never rewrites a rule.

    python scripts/factory-alignment.py
    python scripts/factory-alignment.py --json
    python scripts/factory-alignment.py --print-fingerprints > /tmp/print.json

Exit codes: 0 aligned, 1 drift or a failed probe, 2 the check could not run.

Structural and reviewed-source drift only. Semantic alignment of rules, tests
and behaviour is NOT VERIFIED.
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


def _fingerprint_payload(root: Path) -> dict:
    entries = []
    for entry in contract.expected_fingerprint_entries():
        digest = contract.alignment_source_hash(root, entry["path"], entry["section"])
        if digest is None:
            raise contract.ContractError(f"missing fingerprint source: {entry['path']} ({entry['section']})")
        entries.append(
            {
                "path": entry["path"],
                "section": entry["section"],
                "sha256": digest,
            }
        )
    return {
        "version": contract.SCHEMA_VERSION,
        "note": (
            "Candidate source fingerprints. Matching bytes do not prove approval. "
            "Review the named sources and fingerprint changes independently; this tool never writes the file."
        ),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check factory tooling alignment.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--print-fingerprints",
        action="store_true",
        help="print the current fingerprints for manual review; writes nothing",
    )
    args = parser.parse_args()

    try:
        if args.print_fingerprints:
            print(json.dumps(_fingerprint_payload(contract.PACKAGE_ROOT), indent=2))
            return 0
        started = time.perf_counter()
        result = contract.alignment_check()
    except (contract.ContractError, OSError, ValueError, RecursionError) as failure:
        print(f"error: {failure}", file=sys.stderr)
        return 2
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for check in result["checks"]:
            print(f"{'PASS' if check['ok'] else 'FAIL'}  {check['check']}: {check['detail']}")
        for error in result["errors"]:
            print(f"FAIL  {error}")
        print(f"\n{'OK' if result['ok'] else 'FAIL'}  alignment  ({result['duration_ms']} ms)")
        for limitation in result["limitations"]:
            print(f"LIMIT  {limitation}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
