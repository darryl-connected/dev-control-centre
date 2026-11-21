#!/usr/bin/env python3
"""Inspect or explicitly publish private factory handoff records; notification only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

# Do not write bytecode beside an extracted kit, including on a direct invocation.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))

import factory_inbox as inbox


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, f"{inbox.Refusal('invalid-request')}\n")


def main() -> int:
    parser = Parser(prog="factory-inbox", description=__doc__, allow_abbrev=False)
    routes = parser.add_subparsers(dest="route", required=True)
    inspect = routes.add_parser("inspect", help="read registered or published metadata", allow_abbrev=False)
    inspect.add_argument("registration")
    inspect.add_argument("stage", nargs="?")
    inspect.add_argument("attempt", nargs="?")
    register = routes.add_parser("register", help="record a job or attempt with approval", allow_abbrev=False)
    types = register.add_subparsers(dest="kind", required=True)
    job = types.add_parser("job", help="bind a private root to one approved conversation", allow_abbrev=False)
    job.add_argument("root")
    job.add_argument("--manifest", required=True)
    job.add_argument("--session", required=True)
    job.add_argument("--expires-ms", required=True, type=int)
    attempt = types.add_parser("attempt", help="bind a role and attempt to an approved job", allow_abbrev=False)
    publish = routes.add_parser("publish", help="copy complete report and evidence, then expose the event", allow_abbrev=False)
    for route in (attempt, publish):
        route.add_argument("registration")
        route.add_argument("stage", metavar="{writer,reviewer}")
        route.add_argument("attempt")
    attempt.add_argument("--candidate", help="canonical factory-job candidate JSON (reviewer only)")
    publish.add_argument("outcome", nargs="?", help="required for writer; for reviewer, defaults to the bound receipt verdict")
    publish.add_argument("--report", required=True)
    publish.add_argument("--evidence", required=True)
    for route in (job, attempt, publish):
        route.add_argument("--approve", action="store_true", help="authorise these new local records only")

    args = parser.parse_args()
    if args.route == "publish" and args.stage == "writer" and args.outcome is None:
        parser.error("writer outcome is required")
    try:
        if args.route == "inspect":
            result = inbox.inspect(args.registration, args.stage, args.attempt)
        else:
            if not args.approve:
                raise inbox.Refusal("approval-required")
            if args.route == "publish":
                result = inbox.publish(args.registration, args.stage, args.attempt, args.outcome, args.report, args.evidence)
            elif args.kind == "job":
                result = inbox.register_job(args.root, args.manifest, args.session, args.expires_ms)
            else:
                result = inbox.register_attempt(args.registration, args.stage, args.attempt, args.candidate)
    except (inbox.Refusal, FileExistsError, OSError) as error:
        if not isinstance(error, inbox.Refusal):
            error = inbox.Refusal("record-exists" if isinstance(error, FileExistsError) else "write-failed")
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())