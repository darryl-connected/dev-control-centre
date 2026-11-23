#!/usr/bin/env python3
"""Check the full-suite prerequisites, then run the shipped suite exactly once.

The checks use this interpreter and this role environment and finish before
discovery, so a missing or invalid prerequisite stops the command before any
test module is imported or executed. It reads no credentials, prints no
environment values, installs nothing and makes no network request. Child test
modules keep their own real boundary checks.

    python -B scripts/verify-suite.py
    python -B scripts/verify-suite.py --check

Exit codes: 0 prerequisites met and the suite passed, 1 the suite failed,
2 a prerequisite is missing or invalid or the command could not run.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SUITE = PACKAGE_ROOT / "tests"
PATTERN = "test_*.py"

# (variable, expectation, must be executable). Declared paths stay authoritative.
FILE_REQUIREMENTS: tuple[tuple[str, str, bool], ...] = (
    ("DCC_PI_EXECUTABLE", "absolute path to the pinned Pi CLI", True),
    ("DCC_HERDR_EXECUTABLE", "absolute path to the Herdr CLI", True),
    ("DCC_PI_SDK_MODULE", "absolute path to the installed Pi SDK entry file", False),
    ("DCC_B3_NODE", "absolute path to the Node runtime used by OpenSpec", True),
    ("DCC_B3_OPENSPEC", "absolute path to the installed OpenSpec entry file", False),
)
PATH_REQUIREMENTS = ("git", "unshare")
UNSHARE_PROBE = ("-Urn", "--", "true")
PROBE_TIMEOUT_SECONDS = 20


def _file_problem(value: str | None, expectation: str, executable: bool) -> str | None:
    if not value:
        return f"is not set; expected {expectation}"
    path = Path(value)
    if not path.is_absolute():
        return f"is not an absolute path; expected {expectation}"
    if not path.is_file():
        return f"does not name an existing file; expected {expectation}"
    if executable and not os.access(path, os.X_OK):
        return f"names a file that is not executable; expected {expectation}"
    return None


def _namespace_problem(executable: str) -> str | None:
    try:
        probe = subprocess.run(
            [executable, *UNSHARE_PROBE],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return f"user-namespace probe could not run ({type(error).__name__})"
    if probe.returncode != 0:
        return f"user-namespace probe failed with status {probe.returncode}"
    return None


def evaluate_requirements() -> list[tuple[str, str | None, str | None]]:
    """Return every requirement as (label, observed detail, failure), never stopping early."""
    results: list[tuple[str, str | None, str | None]] = []
    for name, expectation, executable in FILE_REQUIREMENTS:
        problem = _file_problem(os.environ.get(name), expectation, executable)
        detail = "absolute executable file" if executable else "absolute existing file"
        results.append((name, None if problem else f"{name}: {detail}", problem))
    for name in PATH_REQUIREMENTS:
        located = shutil.which(name)
        if located is None:
            results.append((name, None, f"{name}: not found on PATH; required by the full suite"))
            continue
        problem = _namespace_problem(located) if name == "unshare" else None
        detail = f"{name}: user-namespace probe succeeded" if name == "unshare" else f"{name}: found on PATH"
        results.append((name, None if problem else detail, problem))
    if not SUITE.is_dir():
        results.append(("suite", None, f"suite: {SUITE.name} directory is missing next to this command"))
    else:
        modules = sorted(SUITE.glob(PATTERN))
        if not modules:
            results.append(("suite", None, f"suite: no {PATTERN} modules under {SUITE.name}"))
        else:
            results.append(("suite", f"suite: {len(modules)} {PATTERN} modules under {SUITE.name}", None))
    return results


def suite_command() -> list[str]:
    # Same discovery the documented acceptance run uses, resolved next to this
    # file, with this interpreter and the inherited role environment.
    return [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(SUITE), "-p", PATTERN, "-v"]


def run_suite() -> int:
    command = suite_command()
    print(f"verify-suite: running the shipped suite once: {shlex.join(command)}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=str(PACKAGE_ROOT),
            env=os.environ.copy(),
            check=False,
        )
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"verify-suite: suite could not start: {error}", file=sys.stderr)
        return 2
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report prerequisites only; never discovers, imports or runs a test",
    )
    args = parser.parse_args(argv)

    results = evaluate_requirements()
    failures = [(label, failure) for label, _, failure in results if failure is not None]
    if failures:
        print(
            f"verify-suite: {len(failures)} of {len(results)} prerequisites are missing or invalid; "
            "no test was discovered, imported or started",
            file=sys.stderr,
        )
        for label, failure in failures:
            print(f"FAIL  {label}: {failure}", file=sys.stderr)
        return 2
    for _, detail, _ in results:
        print(f"PASS  {detail}", flush=True)
    if args.check:
        print("verify-suite: prerequisite check only; discovery was not run")
        return 0
    return run_suite()


if __name__ == "__main__":
    sys.exit(main())
