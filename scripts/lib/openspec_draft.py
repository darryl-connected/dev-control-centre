"""Preview and publish one new OpenSpec draft; never run OpenSpec in the target."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import task_preparation as prep
from setup import KIT, json_bytes, json_object, local_path

VERSION = '1.8.0'
SCHEMA = 'spec-driven'
ROOT = PurePosixPath('openspec/changes')
METADATA = '.openspec.yaml'
PATTERNS = {'proposal': 'proposal.md', 'design': 'design.md', 'tasks': 'tasks.md', 'specs': 'specs/**/*.md'}
NAME = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
TASK_BOX = re.compile(r'^\s*(?:[-*+]|[0-9]+[.)])\s+\[([ xX])\]\s+\S', re.MULTILINE)
DRAFT_MAX = 2 * prep.MIB
PLAN_MAX = 16 * prep.MIB
TOOL_OUTPUT_MAX = 2 * prep.MIB
AUTHORITY = 'OpenSpec draft only. No content sign-off, implementation or factory launch authority.'


def identifier(value: Any) -> str:
    name = prep.token(value, NAME)
    if len(name) > 80 or name == 'archive':
        prep.block('invalid_change', 'choose a conventional lowercase change or capability ID (not archive)')
    return name


def bytes_at(path: Path, limit: int) -> bytes:
    found = prep.read_regular(path, limit)
    assert found is not None
    return found[0]


def git_free(path: Path) -> None:
    for parent in (path, *path.parents):
        if prep.hub.physical(parent / '.git') is not None:
            prep.block('unsafe_input', 'keep draft inputs, plans and temporary storage outside Git checkouts', path)


def private_input(path: Path) -> None:
    if path.is_relative_to(KIT):
        prep.block('unsafe_input', 'keep draft inputs and plans outside the kit', path)
    git_free(path.parent)


def directory(path: Path, *, optional: bool = False) -> list[int] | None:
    info = prep.hub.physical(path)
    if info is None and optional:
        return None
    if info is None or not stat.S_ISDIR(info.st_mode) or prep.hub.physical(path / '.git') is not None:
        prep.block('unsupported_layout', 'expected a conventional physical OpenSpec directory, not another Git checkout', path)
    return prep.identity(info)


def require_new(target: Path, relative: PurePosixPath) -> None:
    for path in (target / relative, target / ROOT / 'archive' / relative.name):
        try:
            occupied = prep.hub.physical(path) is not None
        except prep.hub.Blocked:
            occupied = True
        if occupied:
            prep.block('change_exists', 'review the existing change separately; no draft is created or replaced', path)


def fresh_scope(workspace: Path, alias: str, task: str, change: str, target: Path, saved: dict) -> dict:
    previous = saved['record']
    current = prep.inspect_task(workspace, alias, local_path(saved['intake']), saved['packet'],
                                previous['intake']['imported_at'], load_history=False)['plan']['record']
    if previous != current or previous['target_root'] != str(target) or previous['task'] != task:
        prep.block('stale_preparation', 'saved preparation is no longer current; reinspect sources, review and save a fresh revision')
    assessment = current['assessment']
    if assessment['state'] != 'ready_for_drafting':
        prep.block('scope_not_ready', 'save a current clarified scope in preparation before drafting')
    if current['artifacts']['change'] != change:
        prep.block('wrong_change', 'select this exact new change ID in preparation and save the reviewed revision')
    if current['artifacts']['sources']:
        prep.block('change_exists', 'review the existing OpenSpec artifacts separately')
    active = assessment['scopes'][assessment['active_scope']]
    workflow = {row['id'] for row in current['sources'] if row['role'] == 'target_workflow'}
    if not workflow.intersection(ref['source'] for ref in active['citations']):
        prep.block('workflow_unreviewed', 'cite current target-owned workflow in the active preparation scope')
    for name in ('openspec/AGENTS.md', 'openspec/changes/AGENTS.md'):
        if prep.hub.physical(target / name) is not None and not any(row['path'] == name and row['id'] == f'target:{name}'
                                                                   for row in current['sources']):
            prep.block('workflow_unreviewed', 'include the applicable target instructions in preparation', name)
    return current


def config_at(path: Path) -> bytes:
    # Admit a narrow local config shape, not arbitrary YAML or a central store.
    # The real CLI still consumes the exact config bytes in the disposable projection.
    data = bytes_at(path, prep.REVIEW_MAX)
    seen = set()
    header = re.compile(r'(schema|context|rules):(?:\s+(.*))?')
    for line in prep.decoded(data, str(path)):
        if not line.strip() or line.lstrip().startswith('#') or line.startswith(' '):
            continue
        match = header.fullmatch(line)
        if match is None or match[1] in seen:
            prep.block('unsupported_layout', 'use a local config.yaml with schema: spec-driven and optional context/rules', path)
        seen.add(match[1])
        if match[1] == 'schema' and (match[2] or '').split('#', 1)[0].strip() != SCHEMA:
            prep.block('unsupported_layout', 'only the built-in spec-driven schema is supported', path)
    if 'schema' not in seen:
        prep.block('unsupported_layout', 'declare schema: spec-driven in openspec/config.yaml', path)
    return data


def authored_paths(raw: Any, prefix: PurePosixPath) -> dict[str, bytes]:
    if not isinstance(raw, dict) or not 4 <= len(raw) <= 35:
        prep.block('invalid_draft', 'supply proposal, design, tasks and 1 to 32 capability spec files')
    draft: dict[str, bytes] = {}
    fixed = set()
    for name, contents in raw.items():
        path = PurePosixPath(prep.relative(name))
        if path.parts[:len(prefix.parts)] != prefix.parts:
            prep.block('out_of_scope', 'every draft path must stay within this exact selected change', name)
        suffix = path.parts[len(prefix.parts):]
        if len(suffix) == 1 and suffix[0] in {'proposal.md', 'design.md', 'tasks.md'}:
            fixed.add(suffix[0])
        elif len(suffix) == 3 and suffix[0] == 'specs' and suffix[2] == 'spec.md':
            identifier(suffix[1])
        else:
            prep.block('unsupported_artifact', 'use the conventional proposal/design/tasks and specs/<capability>/spec.md paths', name)
        text = prep.text(contents, DRAFT_MAX)
        if suffix == ('tasks.md',):
            boxes = TASK_BOX.findall(text)
            if not boxes or any(box != ' ' for box in boxes):
                prep.block('invalid_tasks', 'the draft tasks must contain only unchecked task boxes', name)
        draft[name] = text.encode('utf-8')
    if fixed != {'proposal.md', 'design.md', 'tasks.md'}:
        prep.block('invalid_draft', 'include all conventional fixed files and at least one capability spec')
    return draft


def executable(value: str) -> tuple[Path, list[int]]:
    try:
        path = local_path(value).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise prep.hub.Blocked('tool_unavailable', 'supply the target-approved installed OpenSpec 1.8.0 and optional Node path') from error
    info = prep.hub.physical(path)
    if info is None or not stat.S_ISREG(info.st_mode):
        prep.block('tool_unavailable', 'expected a locally installed executable or OpenSpec JS entry point', path)
    return path, prep.identity(info)


@dataclass
class Inputs:
    target: Path
    change: str
    config: bytes
    authored: dict[str, bytes]
    baselines: dict[str, bytes]
    command: tuple[str, ...]
    provenance: dict

    @property
    def relative(self) -> PurePosixPath:
        return ROOT / self.change


def capture(raw: Any) -> Inputs:
    request = prep.keys(raw, {'workspace', 'repo', 'task', 'change', 'draft', 'openspec', 'node'})
    workspace = local_path(request['workspace'])
    alias = prep.token(request['repo'])
    task = prep.token(request['task'], prep.NATIVE)
    change = identifier(request['change'])
    relative = ROOT / change
    _, target, _ = prep.workspace_context(workspace, alias)
    directories = {name: directory(target / name, optional=name == 'openspec/specs')
                   for name in ('openspec', str(ROOT), 'openspec/specs')}
    require_new(target, relative)
    for marker in ('openspec/config.yml', 'openspec/store.yaml', 'openspec/store.yml'):
        if prep.hub.physical(target / marker) is not None:
            prep.block('unsupported_layout', 'alternate OpenSpec configuration or store layout is not supported', marker)
    saved = prep.history(workspace, alias, task)
    if saved is None:
        prep.block('missing_record', 'approve and save a preparation revision for the selected task first')
    current = fresh_scope(workspace, alias, task, change, target, saved)
    snap = prep.TargetSnapshot(target, prep.TextBudget())
    # A worktree deletion must not turn a tracked change into a new draft location.
    destination_key = os.fsencode(str(relative))
    if (any(key == destination_key or key.startswith(destination_key + b'/') for key in snap.index)
            or snap.run('ls-tree', '-r', '--name-only', '-z', snap.commit, '--', str(relative)).stdout):
        prep.block('change_exists', 'destination already has change entries in HEAD or the index', str(relative))
    if snap.state != current['target']:
        prep.block('stale_preparation', 'target Git state changed; recheck preparation')
    config = config_at(target / 'openspec/config.yaml')
    observed_config = next((item for item in current['sources'] if item['id'] == 'target:openspec/config.yaml'), None)
    if observed_config is None or observed_config['sha256'] != prep.digest(config):
        prep.block('stale_preparation', 'OpenSpec configuration is not current in the saved preparation')
    draft_path = local_path(request['draft'])
    private_input(draft_path)
    draft_bytes = bytes_at(draft_path, DRAFT_MAX)
    draft_row = prep.keys(json_object(draft_bytes, draft_path), {'version', 'artifacts'})
    if type(draft_row['version']) is not int or draft_row['version'] != 1:
        prep.block('invalid_draft', 'expected version 1 draft input')
    authored = authored_paths(draft_row['artifacts'], relative)
    baselines = {}
    baseline_sources = {}
    for name in sorted(authored):
        suffix = PurePosixPath(name).parts[len(relative.parts):]
        if suffix[0] != 'specs':
            continue
        base = str(PurePosixPath('openspec', *suffix))
        directory((target / base).parent, optional=True)
        observed = prep.read_regular(target / base, prep.REVIEW_MAX, optional=True)
        if observed is not None:
            baselines[base] = observed[0]
        baseline_sources[base] = None if observed is None else {'sha256': prep.digest(observed[0]), 'identity': observed[1]}
    tool, tool_state = executable(request['openspec'])
    paths = [(tool, tool_state)]
    if request['node'] is not None:
        node, node_state = executable(request['node'])
        if not os.access(node, os.X_OK):
            prep.block('tool_unavailable', 'the supplied Node path is not executable', node)
        paths.insert(0, (node, node_state))
    elif not os.access(tool, os.X_OK):
        prep.block('tool_unavailable', 'supply an executable OpenSpec or specify --node for its entry point', tool)
    command = tuple(str(path) for path, _ in paths)
    return Inputs(target, change, config, authored, baselines, command,
                  {'revision': saved['revision'], 'preparation': current, 'draft_input_sha256': prep.digest(draft_bytes),
                   'layout': directories, 'baseline_specs': baseline_sources,
                   'tool_entries': {str(path): state for path, state in paths}})


@dataclass
class Run:
    argv: list[str]
    exit: int
    stdout: bytes
    stderr: bytes

    def evidence(self, report: dict | None = None) -> dict:
        return {'argv': self.argv, 'exit': self.exit, 'stderr': self.stderr.decode('utf-8', 'replace'), 'report': report}


def invoke(inputs: Inputs, sandbox: Path, *args: str) -> Run:
    home = sandbox / 'private-home'
    argv = [*inputs.command, *args]
    path = os.pathsep.join(part for part in os.environ.get('PATH', os.defpath).split(os.pathsep) if os.path.isabs(part))
    env = {'PATH': path or os.defpath, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
           'XDG_DATA_HOME': str(home / 'data'), 'XDG_CACHE_HOME': str(home / 'cache'), 'TMPDIR': str(home),
           'LC_ALL': 'C', 'CI': '1', 'OPENSPEC_TELEMETRY': '0', 'DO_NOT_TRACK': '1'}
    try:
        result = subprocess.run(argv, cwd=sandbox, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise prep.hub.Blocked('tool_unavailable', f'OpenSpec {args[0]} could not run locally or timed out') from error
    if len(result.stdout) > TOOL_OUTPUT_MAX or len(result.stderr) > TOOL_OUTPUT_MAX:
        prep.block('tool_output', 'OpenSpec exceeded the supported output size')
    return Run(argv, result.returncode, result.stdout, result.stderr)


def tool_json(run: Run, code: str) -> dict:
    try:
        return json_object(run.stdout, Path('OpenSpec stdout'))
    except (ValueError, TypeError) as error:
        diagnostic = prep.hub.Blocked(code, 'OpenSpec did not return the expected JSON; check the approved local tool and workflow')
        diagnostic.diagnostic['tool'] = run.evidence() | {'stdout': run.stdout.decode('utf-8', 'replace')}
        raise diagnostic from error


def root_result(sandbox: Path) -> dict:
    return {'path': str(sandbox), 'source': 'nearest'}


def run_json(inputs: Inputs, sandbox: Path, *args: str) -> dict:
    result = invoke(inputs, sandbox, *args)
    report = tool_json(result, 'discovery_failed')
    if result.exit or result.stderr or report.get('root') != root_result(sandbox):
        error = prep.hub.Blocked('discovery_failed', 'OpenSpec did not resolve the conventional project in the disposable copy')
        error.diagnostic['tool'] = result.evidence(report)
        raise error
    return report


def discover(inputs: Inputs, sandbox: Path) -> tuple[dict, dict[str, bytes]]:
    (sandbox / 'private-home').mkdir(mode=0o700)
    (sandbox / ROOT / 'archive').mkdir(parents=True)
    (sandbox / 'openspec/specs').mkdir()
    (sandbox / 'openspec/config.yaml').write_bytes(inputs.config)
    write_files(sandbox, inputs.baselines)
    version = invoke(inputs, sandbox, '--version')
    if version.exit or version.stderr or version.stdout.strip() != VERSION.encode():
        error = prep.hub.Blocked('unsupported_tool', f'use the target-approved local OpenSpec {VERSION}')
        error.diagnostic['tool'] = version.evidence() | {'stdout': version.stdout.decode('utf-8', 'replace')}
        raise error
    created = run_json(inputs, sandbox, 'new', 'change', inputs.change, '--json')
    change_dir = sandbox / inputs.relative
    metadata_path = change_dir / METADATA
    if created.get('change') != {'id': inputs.change, 'path': str(change_dir), 'metadataPath': str(metadata_path), 'schema': SCHEMA}:
        prep.block('unsupported_layout', 'OpenSpec reported an unexpected scaffold or schema')
    metadata = bytes_at(metadata_path, prep.REVIEW_MAX)
    metadata_files = {str(inputs.relative / METADATA): metadata}
    check_tree(sandbox, inputs.relative, metadata_files)
    status = run_json(inputs, sandbox, 'status', '--change', inputs.change, '--json')
    planning = status.get('planningHome')
    action = status.get('actionContext')
    if (status.get('changeName') != inputs.change or status.get('schemaName') != SCHEMA or status.get('changeRoot') != str(change_dir)
            or planning != {'kind': 'repo', 'root': str(sandbox), 'changesDir': str(sandbox / ROOT), 'defaultSchema': SCHEMA}
            or not isinstance(action, dict) or action.get('mode') != 'repo-local' or action.get('sourceOfTruth') != 'repo'
            or action.get('linkedContext') != []
            or action.get('requiresAffectedAreaSelection') is not False or action.get('allowedEditRoots') != [str(sandbox)]):
        prep.block('unsupported_layout', 'OpenSpec did not report the supported repository-local planning layout')
    expected_paths = {key: {'outputPath': pattern, 'resolvedOutputPath': str(change_dir / pattern), 'existingOutputPaths': []}
                      for key, pattern in PATTERNS.items()}
    artifacts = status.get('artifacts')
    if (status.get('artifactPaths') != expected_paths or not isinstance(artifacts, list) or len(artifacts) != len(PATTERNS)
            or not all(isinstance(item, dict) for item in artifacts)
            or {item['id']: item['outputPath'] for item in artifacts} != PATTERNS):
        prep.block('unsupported_layout', 'OpenSpec artifact metadata differs from the supported spec-driven layout')
    plan_data = {'version': VERSION, 'schema': SCHEMA, 'metadata': str(inputs.relative / METADATA),
                 'commands': [['new', 'change', inputs.change, '--json'], ['status', '--change', inputs.change, '--json']],
                 'artifacts': artifacts, 'output_paths': {key: str(inputs.relative / pattern) for key, pattern in PATTERNS.items()}}
    return plan_data, metadata_files | inputs.authored


def write_files(root: Path, files: dict[str, bytes]) -> None:
    for name, data in sorted(files.items()):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)


def check_tree(sandbox: Path, relative: PurePosixPath, files: dict[str, bytes]) -> None:
    allowed = {str(parent) for name in files for parent in PurePosixPath(name).parents if parent.is_relative_to(relative)}
    observed = {}
    for path in (sandbox / relative).rglob('*'):
        name = path.relative_to(sandbox).as_posix()
        info = prep.hub.physical(path)
        if info is not None and stat.S_ISDIR(info.st_mode) and name in allowed:
            continue
        if name not in files:
            prep.block('unexpected_artifact', 'the disposable change contains a path that was not planned', name)
        observed[name] = bytes_at(path, DRAFT_MAX)
    if observed != files:
        prep.block('unexpected_artifact', 'the disposable change no longer matches the exact planned artifact bytes')


def validate(inputs: Inputs, sandbox: Path) -> dict:
    run = invoke(inputs, sandbox, 'validate', inputs.change, '--type', 'change', '--strict', '--json', '--no-interactive')
    report = tool_json(run, 'validation_failed')
    items = report.get('items')
    if (run.exit != 0 or report.get('root') != root_result(sandbox) or not isinstance(items, list) or len(items) != 1
            or not isinstance(items[0], dict) or items[0].get('id') != inputs.change or items[0].get('type') != 'change'
            or items[0].get('valid') is not True):
        error = prep.hub.Blocked('validation_failed', 'strict OpenSpec validation did not pass; edit the draft and preview again')
        error.diagnostic['validation'] = run.evidence(report)
        raise error
    return run.evidence(report)


def publish(inputs: Inputs, files: dict[str, bytes]) -> None:
    target = inputs.target
    destination = target / inputs.relative
    require_new(target, inputs.relative)
    # Stage only after validation, on the destination filesystem. Rename the complete
    # draft directory once. The final absence check is sequential, not a race guarantee.
    with tempfile.TemporaryDirectory(prefix='.dcc-draft-', dir=destination.parent) as staging:
        candidate = Path(staging) / inputs.change
        candidate.mkdir(mode=0o755)
        write_files(candidate, {str(PurePosixPath(name).relative_to(inputs.relative)): data for name, data in files.items()})
        require_new(target, inputs.relative)
        candidate.rename(destination)


def draft_plan(request: dict, *, displayed: dict | None = None) -> dict:
    inputs = capture(request)
    temporary = Path(tempfile.gettempdir()).resolve()
    git_free(temporary)
    if temporary.is_relative_to(KIT):
        prep.block('unsafe_input', 'temporary directory must be outside the kit')
    with tempfile.TemporaryDirectory(prefix='dcc-openspec-', dir=temporary) as scratch:
        sandbox = Path(scratch)
        discovery, files = discover(inputs, sandbox)
        plan = {'version': 1, 'request': request, 'provenance': inputs.provenance, 'discovery': discovery,
                'artifacts': {name: data.decode('utf-8') for name, data in sorted(files.items())}}
        data = json_bytes(plan)
        if len(data) > PLAN_MAX // 2:
            prep.block('plan_limit', 'scope and draft exceed the bounded plan size')
        if displayed is None:
            if capture(request) != inputs:
                prep.block('stale_plan', 'draft, target or provenance drifted during preview; preview again')
            return {'plan': plan, 'approval_sha256': prep.digest(data), 'validation': 'not run in preview',
                    'next_step': 'Review the exact paths, contents and scope, then decide whether to approve this draft only.'}
        if json_bytes(displayed) != data:
            prep.block('stale_plan', 'displayed plan, authored bytes or bound inputs changed; preview again')
        write_files(sandbox, inputs.authored)
        check_tree(sandbox, inputs.relative, files)
        result = validate(inputs, sandbox)
        check_tree(sandbox, inputs.relative, files)
        if capture(request) != inputs:
            prep.block('stale_plan', 'draft, target or provenance drifted during validation; preview again')
        publish(inputs, files)
        return {'result': 'draft_created', 'target': str(inputs.target), 'change': inputs.change,
                'scope': inputs.provenance['preparation']['assessment']['active_scope'],
                'approval_sha256': prep.digest(data), 'revision': inputs.provenance['revision'],
                'artifacts': {name: prep.digest(content) for name, content in sorted(files.items())}, 'validation': result,
                'next_step': 'Review the exact repository artifacts and record current artifact citations in preparation if appropriate. Stop before requesting any separate launch approval.'}


def apply(plan_path: Path, approval: str | None) -> dict:
    if approval is None:
        prep.block('approval_required', 'approval requires the SHA-256 shown for the exact displayed draft plan')
    private_input(plan_path)
    envelope = json_object(bytes_at(plan_path, PLAN_MAX), plan_path)
    plan = prep.keys(envelope.get('plan'), {'version', 'request', 'provenance', 'discovery', 'artifacts'})
    if prep.digest(json_bytes(plan)) != approval:
        prep.block('approval_mismatch', 'approval does not match the displayed draft plan; inspect the original preview')
    return draft_plan(plan['request'], displayed=plan)
