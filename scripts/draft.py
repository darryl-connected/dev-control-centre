#!/usr/bin/env python3
"""Preview or publish one approved repository-local OpenSpec draft. Never start the factory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))

import openspec_draft as draft
from setup import local_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    actions = parser.add_subparsers(dest='action', required=True)
    preview = actions.add_parser('preview', help='display exact content and paths without writing to the target', allow_abbrev=False)
    for option in ('workspace', 'repo', 'task', 'change', 'draft', 'openspec'):
        preview.add_argument(f'--{option}', required=True)
    preview.add_argument('--node', help='explicit local Node executable for an OpenSpec JS entry point')
    apply = actions.add_parser('apply', help='publish an exact displayed draft after strict validation', allow_abbrev=False)
    apply.add_argument('--plan', required=True)
    apply.add_argument('--approve', metavar='SHA256', help='approval of the exact displayed draft only')
    args = parser.parse_args()
    authority = {'authority': draft.AUTHORITY, 'launch_authority': False}
    try:
        if args.action == 'preview':
            request = {key: value for key, value in vars(args).items() if key != 'action'}
            for key in ('workspace', 'draft', 'openspec', 'node'):
                if request[key] is not None:
                    request[key] = str(local_path(request[key]))
            result = draft.draft_plan(request)
        else:
            result = draft.apply(local_path(args.plan), args.approve)
        print(json.dumps(result | authority, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return 0
    except draft.prep.hub.Blocked as error:
        diagnostic = error.diagnostic
    except OSError as error:
        diagnostic = {'code': 'local_io_error', 'detail': f'Could not read or write a local path: {error.strerror or error}' }
    except (KeyError, TypeError, ValueError, RuntimeError):
        diagnostic = {'code': 'invalid_input', 'detail': 'Input or tool output is malformed or unsafe; no successful application.'}
    print(json.dumps({'error': diagnostic} | authority, ensure_ascii=True, allow_nan=False), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
