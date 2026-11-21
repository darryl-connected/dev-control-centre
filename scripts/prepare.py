#!/usr/bin/env python3
"""Prepare one selected task locally. No service requests or authority to draft or launch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))

import task_preparation as prep
from setup import json_object, local_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest='action', required=True)
    preview = commands.add_parser('inspect', help='read selected task and source bodies; create nothing', allow_abbrev=False)
    preview.add_argument('--workspace', required=True)
    preview.add_argument('--repo')
    preview.add_argument('--intake', required=True)
    preview.add_argument('--review')
    preview.add_argument('--plan-only', action='store_true', help='print the exact compact plan for a separate approved save')
    save = commands.add_parser('save', help='create one fresh private revision of a displayed plan', allow_abbrev=False)
    save.add_argument('--plan', required=True)
    save.add_argument('--approve', action='store_true', help='approve only this new local record')
    resume = commands.add_parser('resume', help='recheck sources and restore private notes; create nothing', allow_abbrev=False)
    resume.add_argument('--workspace', required=True)
    resume.add_argument('--repo')
    resume.add_argument('--task', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'save':
            if not args.approve:
                raise prep.hub.Blocked('approval_required', 'save requires explicit approval of the displayed local revision')
            result = prep.save(prep.load_plan(local_path(args.plan)))
        else:
            workspace = local_path(args.workspace)
            alias = prep.repository_alias(workspace, args.repo)
            if args.action == 'resume':
                result = prep.resume(workspace, alias, prep.token(args.task, prep.NATIVE))
            else:
                packet = None
                if args.review:
                    path = local_path(args.review)
                    found = prep.read_regular(path, prep.REVIEW_MAX)
                    assert found is not None
                    packet = json_object(found[0], path)
                result = prep.inspect_task(workspace, alias, local_path(args.intake), packet, prep.timestamp())
                if args.plan_only:
                    result = {key: result[key] for key in ('authority', 'launch_authority', 'plan')}
        print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except prep.hub.Blocked as error:
        diagnostic = error.diagnostic
    except (OSError, TypeError, ValueError, RuntimeError):
        diagnostic = {'code': 'invalid_input', 'detail': 'Input is unreadable, malformed or unsafe; no readiness or approval recorded.'}
    print(json.dumps({'error': diagnostic, 'launch_authority': False, 'authority': prep.AUTHORITY}), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
