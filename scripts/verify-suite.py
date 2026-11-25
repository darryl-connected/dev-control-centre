#!/usr/bin/env python3
"""Check offline QA prerequisites, then run only the selected packaged profile.

`native` (default) covers portable behavior. `linux-security` covers the
separate Linux isolation/origin suite. Neither installs, authenticates or
makes a provider request. Use --check for prerequisites and static coverage
validation without importing, discovering or executing any test module.

Exit 2 for an invalid profile, missing prerequisite or incomplete package;
otherwise pass the selected child suite's status through.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    import verification_profiles as profiles
except ModuleNotFoundError as error:
    if error.name != "verification_profiles":
        raise
    print("FAIL  coverage: packaged verification_profiles.py is missing; no test was imported or started", file=sys.stderr)
    sys.exit(2)


def run_suite(profile: str) -> int:
    command = [sys.executable, "-B", profiles.__file__, profile]
    print(f"verify-suite: running profile {profile} once: {shlex.join(command)}", flush=True)
    try:
        completed = subprocess.run(command, cwd=profiles.ROOT, env=os.environ.copy(), check=False)
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"verify-suite: selected suite could not start: {error}", file=sys.stderr)
        return 2
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=profiles.PROFILE_SUITES, default=profiles.NATIVE,
                        help="coverage to run (default: native)")
    parser.add_argument("--check", action="store_true", help="check only; never discovers or imports tests")
    args = parser.parse_args(argv)

    print(f"Selected profile: {args.profile}", flush=True)
    for profile, selectors in profiles.PROFILE_SUITES.items():
        status = "SELECTED" if profile == args.profile else f"NOT VERIFIED ({profile} excluded)"
        for selector in selectors:
            print(f"{status}  {selector}", flush=True)
    checks = profiles.requirements(args.profile)
    if all(problem is None for _, problem in checks):
        try:
            selected = profiles.coverage()[args.profile]
        except (OSError, ValueError, SyntaxError) as failure:
            checks.append(("coverage", str(failure)))
    else:
        selected = set()
    failures = [(label, problem) for label, problem in checks if problem is not None]
    if failures:
        print(f"verify-suite: {len(failures)} checks failed; no test was discovered, imported or started",
              file=sys.stderr)
        for label, problem in failures:
            print(f"FAIL  {label}: {problem}", file=sys.stderr)
        return 2
    for label, _ in checks:
        print(f"PASS  {label}", flush=True)
    print(f"PASS  coverage: {len(selected)} test IDs assigned to {args.profile}", flush=True)
    if args.check:
        print("verify-suite: prerequisite check only; selected tests NOT VERIFIED")
        return 0
    return run_suite(args.profile)


if __name__ == "__main__":
    sys.exit(main())
