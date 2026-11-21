#!/usr/bin/env python3
"""Map an existing local knowledge checkout or print an index for one explicit PRD."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from setup import KIT, SKILLS, Inspection, json_bytes, json_object, local_path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))

import knowledge_hub as hub


def workspace_state(workspace: Path, check: Inspection) -> tuple[Path, ...]:
    home = local_path(str(Path.home()))
    agent = local_path(os.environ.get('PI_CODING_AGENT_DIR') or str(home / '.pi/agent'))
    if workspace == home or any(hub.overlap(workspace, path) for path in (KIT, agent, home / '.agents')):
        raise hub.Blocked('workspace_overlap', 'workspace must be separate from the kit, HOME and user configuration', workspace)
    for parent in (workspace, *workspace.parents):
        if check.stat_path(parent / '.git') is not None:
            raise hub.Blocked('workspace_overlap', 'workspace must be outside Git checkouts', parent)
    check.directory(workspace, required=True)
    check.directory(workspace / '.dcc', required=True)
    check.directory(workspace / '.pi', required=True)
    stored = workspace / '.dcc/workspace.json'
    settings = workspace / '.pi/settings.json'
    config_data = check.file(stored, required=True)
    settings_data = check.file(settings, required=True)
    check.file(workspace / '.pi/APPEND_SYSTEM.md', required=True)
    assert config_data is not None and settings_data is not None
    config = json_object(config_data, stored)
    repos = config.get('repositories')
    if (type(config.get('version')) is not int or config['version'] != 1 or config.get('workspace') != str(workspace)
            or not isinstance(config.get('kit'), str) or not isinstance(repos, dict) or not repos
            or not all(isinstance(value, str) for value in repos.values())):
        raise hub.Blocked('invalid_workspace', 'expected an existing A14 workspace configuration', stored)
    registered_kit = saved_path(config['kit'], stored)
    targets = tuple(saved_path(value, stored) for value in repos.values())
    if hub.overlap(workspace, registered_kit) or any(hub.overlap(workspace, target) for target in targets):
        raise hub.Blocked('workspace_overlap', 'workspace must be separate from its registered kit and targets', stored)
    registered_skills = [str(registered_kit / 'skills' / name / 'SKILL.md') for name in SKILLS]
    if json_object(settings_data, settings).get('skills') != registered_skills:
        raise hub.Blocked('invalid_workspace', 'expected A14 skill registration in existing settings', settings)
    return (KIT, registered_kit, workspace, *targets)


def saved_path(value: str, config: Path) -> Path:
    path = local_path(value)
    if str(path) != value:
        raise hub.Blocked('invalid_workspace', 'expected absolute paths in the A14 workspace configuration', config)
    info = hub.physical(path)
    if info is not None and not stat.S_ISDIR(info.st_mode):
        raise hub.Blocked('invalid_workspace', 'expected physical kit and target directories', config)
    return path


def inspect(workspace: Path, requested: Path | None) -> tuple[dict, bytes]:
    check = Inspection()
    excluded = workspace_state(workspace, check)
    path = workspace / hub.MAPPING
    # First validate the type and limit bytes, then capture A14-style file identity for the plan.
    current = hub.regular_bytes(path, optional=True)
    if check.file(path) != current:
        raise hub.Blocked('stale_plan', 'mapping changed during inspection; inspect again', path)
    existing = None if current is None else hub.parse_mapping(current, path)
    if requested is None and existing is None:
        raise hub.Blocked('missing_checkout', 'supply the local source checkout path with --checkout')
    root = requested if requested is not None else existing
    assert root is not None
    desired = json_bytes({'version': 1, 'checkout': str(root)})
    if current is not None and current != desired:
        raise hub.Blocked('mapping_conflict', 'existing mapping is not byte-identical; no replacement or migration', path)
    snapshot = hub.Snapshot(root, excluded)
    return ({'version': 1, 'workspace': str(workspace), 'checkout': str(root), 'source_commit': snapshot.commit,
             'source_identity': [list(item) for item in snapshot.identity],
             'action': 'create' if current is None else 'unchanged', 'path': hub.MAPPING,
             'preconditions': check.states}, desired)


def apply(plan: dict, desired: bytes) -> None:
    if plan['action'] == 'unchanged':
        return
    directory = Path(plan['workspace']) / '.dcc'
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if [info.st_dev, info.st_ino, info.st_mode] != plan['preconditions'][str(directory)] or not stat.S_ISDIR(info.st_mode):
            raise hub.Blocked('stale_plan', 'workspace mapping directory changed; inspect again', directory)
        out = os.open('knowledge.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(out, 'wb') as stream:
            stream.write(desired)
    finally:
        os.close(fd)


def apply_plan(plan_path: Path) -> dict:
    data = hub.regular_bytes(plan_path)
    assert data is not None
    plan = json_object(data, plan_path).get('plan')
    if not isinstance(plan, dict) or not all(isinstance(plan.get(key), str) for key in ('workspace', 'checkout')):
        raise hub.Blocked('invalid_plan', 'expected JSON plan from inspect', plan_path)
    try:
        current, desired = inspect(local_path(plan['workspace']), local_path(plan['checkout']))
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        detail = f"{error.diagnostic['code']}: {error}" if isinstance(error, hub.Blocked) else str(error)
        raise hub.Blocked('stale_plan', f'plan no longer applicable; inspect again ({detail})', plan_path) from error
    if json_bytes(current) != json_bytes(plan):
        raise hub.Blocked('stale_plan', 'plan no longer matches current files or source commit; inspect again', plan_path)
    apply(current, desired)
    return {'path': hub.MAPPING, 'action': current['action']}


def sources(workspace: Path, prd: str) -> dict:
    if not hub.PRD.fullmatch(prd):
        raise hub.Blocked('invalid_prd', 'supply one explicit PRD identifier in PRD000 form')
    excluded = workspace_state(workspace, Inspection())
    path = workspace / hub.MAPPING
    data = hub.regular_bytes(path, optional=True)
    if data is None:
        raise hub.Blocked('not_configured', 'no saved source mapping; use explicit mapping inspect and apply', path)
    result = hub.source_index(hub.Snapshot(hub.parse_mapping(data, path), excluded), prd)
    if hub.regular_bytes(path, optional=True) != data:
        raise hub.Blocked('snapshot_drift', 'saved source mapping changed during lookup', path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    preview = sub.add_parser('inspect', help='print a read-only local mapping plan')
    preview.add_argument('--workspace', required=True)
    preview.add_argument('--checkout', help='physical local Git checkout root (omit to reuse the saved path)')
    install = sub.add_parser('apply', help='create only an absent mapping using a still-current plan')
    install.add_argument('--plan', required=True, help='JSON output saved from inspect')
    install.add_argument('--approve', action='store_true')
    lookup = sub.add_parser('sources', help='index references for one PRD using a saved mapping')
    lookup.add_argument('--workspace', required=True)
    lookup.add_argument('--prd', required=True)
    args = parser.parse_args()
    try:
        if args.mode == 'inspect':
            plan, _ = inspect(local_path(args.workspace), local_path(args.checkout) if args.checkout is not None else None)
            result = {'plan': plan}
        elif args.mode == 'apply':
            if not args.approve:
                raise hub.Blocked('approval_required', 'apply requires explicit --approve after inspecting the plan')
            result = {'applied': apply_plan(local_path(args.plan))}
        else:
            result = sources(local_path(args.workspace), args.prd)
        print(json_bytes({'ok': True, **result}).decode(), end='')
        return 0
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        diagnostic = error.diagnostic if isinstance(error, hub.Blocked) else {'code': 'local_precondition', 'detail': str(error)}
        if args.mode == 'sources':
            diagnostic = {**diagnostic, 'prd': args.prd}
        print(json.dumps({'ok': False, 'error': diagnostic}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
