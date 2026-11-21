"""Selected-task preparation: snapshot local evidence, validate an attributed review, save only private notes."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import knowledge_hub as hub
from knowledge import workspace_state
from setup import Inspection, json_bytes, json_object, local_path

MIB = 1024 * 1024
INTAKE_MAX = 32 * MIB
RECORD_MAX = 8 * MIB
REVIEW_MAX = MIB
SOURCE_MAX = 128
TOTAL_MAX = 64 * MIB
NATIVE = re.compile(r'[A-Za-z0-9]{1,64}')
KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')
HASH = re.compile(r'[a-f0-9]{64}')
LABEL = re.compile(r'^\s*(PRD[0-9]{3})(?=$|[\s,:/;–—-])')
EXPLICIT = re.compile(r'^\s*(?:PRD|Product requirements)\s*:\s*(PRD[0-9]{3})(?=$|[\s,/;])')
MULTIPLE = re.compile(r'\s*(?:,|/|;|\band\b)\s*(PRD[0-9]{3})(?=$|[\s,:/;–—-])')
REVISION = re.compile(r'([0-9]{6})-([a-f0-9]{64})\.json')
AUTHORITY = 'Local preparation only; no source/artifact writes, factory launch, spending or implementation approval.'
REVIEW_LIMIT = 'Structured fields and current citations checked; semantic reasoning, owner identity and sign-off are not authenticated.'


def block(code: str, detail: str, path: str | Path | None = None) -> NoReturn:
    raise hub.Blocked(code, detail, path)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017 (Python 3.10)


def keys(value: Any, required: set[str], optional: tuple[str, ...] = ()) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - set(optional):
        block('invalid_schema', 'unexpected or missing object fields')
    return value


def text(value: Any, limit: int = 4000) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in '\t\n\r' or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        block('invalid_schema', 'expected bounded nonblank text')
    return value


def token(value: Any, pattern: re.Pattern = KEY) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        block('invalid_schema', 'invalid identifier')
    return value


def array(value: Any, limit: int = SOURCE_MAX) -> list:
    if not isinstance(value, list) or len(value) > limit:
        block('invalid_schema', 'expected a bounded list')
    return value


def mapping(value: Any) -> dict:
    if not isinstance(value, dict) or len(value) > SOURCE_MAX:
        block('invalid_schema', 'expected a bounded mapping')
    for key in value:
        token(key)
    return value


def read_regular(path: Path, limit: int, *, optional: bool = False) -> tuple[bytes, list[int]] | None:
    info = hub.physical(path)
    if info is None and optional:
        return None
    if info is None or not stat.S_ISREG(info.st_mode):
        raise hub.Blocked('missing_or_unsafe_file', 'expected a physical regular file', path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        start = os.fstat(stream.fileno())
        if not stat.S_ISREG(start.st_mode) or start.st_size > limit:
            raise hub.Blocked('source_limit', 'file is not regular or exceeds its byte limit', path)
        data = stream.read(limit + 1)
        end = os.fstat(stream.fileno())
    current = hub.physical(path)
    # Ignore access-time changes caused by the read, not identity, mode or content metadata.
    if (len(data) > limit or len(data) != start.st_size or identity(start) != identity(end)
            or current is None or identity(current) != identity(end)):
        raise hub.Blocked('snapshot_drift', 'file changed or was not read completely', path)
    return data, identity(end)


def identity(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def decoded(data: bytes, path: str) -> list[str]:
    try:
        source = data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise hub.Blocked('unsupported_document', 'required source is not UTF-8 text', path) from exc
    if not source.strip() or '\0' in source:
        raise hub.Blocked('unsupported_document', 'required source is empty or binary', path)
    return source.splitlines()


class BoundedInspection(Inspection):
    def file(self, path: Path, *, required: bool = False) -> bytes | None:
        pair = read_regular(path, REVIEW_MAX, optional=not required)
        self.states[str(path)] = None if pair is None else [pair[1], digest(pair[0])]
        return None if pair is None else pair[0]


def repository_alias(workspace: Path, supplied: str | None) -> str:
    if supplied is not None:
        return token(supplied)
    check = BoundedInspection()
    workspace_state(workspace, check)
    path = workspace / '.dcc/workspace.json'
    found = read_regular(path, REVIEW_MAX)
    assert found is not None
    repos = json_object(found[0], path)['repositories']
    if len(repos) != 1:
        block('repository_required', 'Which configured repository alias owns this selected task? Supply --repo.')
    return token(next(iter(repos)))


def workspace_context(workspace: Path, alias: str) -> tuple[tuple[Path, ...], Path, dict]:
    check = BoundedInspection()
    excluded = workspace_state(workspace, check)
    path = workspace / '.dcc/workspace.json'
    mapping_state = check.states[str(path)]
    data = check.file(path, required=True)
    assert data is not None
    if mapping_state != check.states[str(path)]:
        block('snapshot_drift', 'workspace mapping changed during inspection', path)
    value = json_object(data, path)['repositories'].get(alias)
    if not isinstance(value, str):
        raise hub.Blocked('unknown_repository', 'choose one of the existing configured repository aliases', path)
    target = local_path(value)
    if any(hub.overlap(target, item) for item in excluded[:3]):
        raise hub.Blocked('checkout_overlap', 'mapped code target must be separate from workspace and kit', target)
    return excluded, target, check.states


def observation(value: Any) -> dict:
    if not isinstance(value, dict):
        block('invalid_intake', 'expected a B1 service observation object')
    result = {key: text(value[key], 300) for key in ('endpoint', 'observed_at') if key in value}
    if type(value.get('page')) is int:
        result['page'] = value['page']
    return result


def intake_view(data: bytes, path: Path) -> tuple[dict, list[dict]]:
    raw = json_object(data, path)
    selected = raw.get('selected')
    if not isinstance(selected, dict) or raw.get('status') not in ('observed', 'partial'):
        raise hub.Blocked('invalid_intake', 'a valid selected B1 task with a native ID is required', path)
    ancestors = array(raw.get('ancestors'), 32)
    candidates: list[dict] = []
    tasks: list[dict] = []
    unresolved = []
    for row in array(raw.get('unresolved'), 16_000):
        if not isinstance(row, dict):
            block('invalid_intake', 'malformed B1 incompleteness')
        info = {key: text(row[key], 180) for key in ('kind', 'reason') if key in row}
        for key in ('task_id', 'child_task_id', 'comment_id'):
            if row.get(key) is not None:
                info[key] = text(row[key], 100)
        for key in ('page', 'reply_count'):
            if type(row.get(key)) is int:
                info[key] = row[key]
        unresolved.append(info or {'kind': 'unspecified B1 incompleteness'})
    seen = set()
    previous = None
    for source in [selected, *ancestors]:
        if not isinstance(source, dict):
            block('invalid_intake', 'malformed B1 task or ancestor')
        native = token(source.get('id'), NATIVE)
        if native in seen or (previous is not None and source.get('child_task_id') != previous):
            block('invalid_intake', 'duplicate or disconnected B1 ancestor')
        seen.add(native)
        kind = 'task' if previous is None else 'ancestor'
        previous = native
        task: dict = {'id': native, 'kind': kind, 'observation': observation(source.get('observation')), 'comments': []}
        for key in ('name', 'description'):
            body = source.get(key)
            if not isinstance(body, str):
                block('invalid_intake', 'expected B1 selected task/ancestor text')
            task[key] = body
            collect_labels(body, {'kind': kind, 'task_id': native, 'field': key}, candidates, title=(key == 'name'))
        comments = set()
        for row in array(source.get('comments'), 16_000):
            if (not isinstance(row, dict) or row.get('task_id') != native or not isinstance(row.get('text'), str)
                    or type(row.get('reply_count')) is not int or row['reply_count'] < 0):
                block('invalid_intake', 'malformed or wrong-task B1 comment')
            comment = text(row.get('id'), 100)
            if comment in comments:
                block('invalid_intake', 'duplicate B1 comment')
            comments.add(comment)
            task['comments'].append({'id': comment, 'text': row['text'], 'reply_count': row['reply_count'],
                                     'observation': observation(row.get('observation'))})
            collect_labels(row['text'], {'kind': 'comment', 'task_id': native, 'comment_id': comment, 'field': 'text'}, candidates)
            if row['reply_count'] and not any(item.get('comment_id') == comment and item.get('kind') == 'replies'
                                              and item.get('task_id') == native for item in unresolved):
                unresolved.append({'kind': 'replies', 'reason': 'thread_not_expanded', 'task_id': native,
                                   'comment_id': comment, 'reply_count': row['reply_count']})
        tasks.append(task)
    return {'status': raw['status'], 'selected': tasks[0], 'ancestors': tasks[1:], 'unresolved': unresolved}, candidates


def collect_labels(body: str, location: dict, rows: list[dict], *, title: bool = False) -> None:
    for number, line in enumerate(body.splitlines(), 1):
        explicit = EXPLICIT.match(line)
        match = explicit or (LABEL.match(line) if title and number == 1 else None)
        if match:
            tail = line[match.end():]
            ids = [match[1]]
            while more := MULTIPLE.match(tail):
                ids.append(more[1])
                tail = tail[more.end():]
            if explicit and tail.strip():
                continue
            for prd in ids:
                if len(rows) >= SOURCE_MAX:
                    block('intake_limit', 'too many explicit association locations')
                rows.append({'prd': prd, 'location': location | {'line': number}})


def association(candidates: list[dict], supplied: Any) -> dict:
    ids = sorted({row['prd'] for row in candidates})
    binding = None
    if supplied is not None:
        row = keys(supplied, {'prd', 'by', 'reason'})
        binding = {'prd': token(row['prd'], hub.PRD), 'from': 'developer-supplied, not task data',
                   'by': text(row['by'], 160), 'reason': text(row['reason'])}
    elif len(ids) == 1:
        binding = {'prd': ids[0], 'from': 'explicit imported association'}
    return {'candidates': candidates, 'conflict': len(ids) > 1 or bool(ids and binding and binding['prd'] not in ids),
            'binding': binding, 'lookup': []}


def relative(value: Any) -> str:
    value = text(value, 512)
    path = PurePosixPath(value)
    if (path.is_absolute() or value != str(path) or not path.parts or '\\' in value or ':' in value
            or any(c in value for c in '\r\n\t') or any(part.casefold() in {'..', '.git', '.dcc', '.pi'} for part in path.parts)):
        block('unsafe_path', 'select a physical repository-relative source path')
    if (any(part.casefold().startswith('.env') for part in path.parts)
            or path.name.casefold() in {'auth.json', 'credentials.json', 'id_rsa', 'id_ed25519'}
            or path.suffix.casefold() in {'.pem', '.key', '.p12', '.pfx'}):
        block('unsafe_path', 'do not select credential files')
    return value


class TextBudget:
    def __init__(self) -> None:
        self.size = 0
        self.count = 0

    def add(self, data: bytes, path: str) -> None:
        self.count += 1
        self.size += len(data)
        if self.count > SOURCE_MAX or self.size > TOTAL_MAX:
            raise hub.Blocked('source_limit', 'selected bundle exceeds its source count or aggregate byte bound', path)


class HubSnapshot(hub.Snapshot):
    def __init__(self, root: Path, excluded: tuple[Path, ...], budget: TextBudget):
        self.budget = budget
        self.bodies: dict[str, bytes] = {}
        super().__init__(root, excluded)

    def working_bytes(self, path: str) -> bytes:
        data = super().working_bytes(path)
        if path not in self.documents:
            self.budget.add(data, path)
            decoded(data, path)
            self.bodies[path] = data
        return data


class TargetSnapshot(hub.Snapshot):
    """Reuse the read-only Git boundary, not the hub's clean-checkout policy."""

    def __init__(self, root: Path, budget: TextBudget):
        self.root = root
        binary = shutil.which('git')
        if binary is None:
            raise hub.Blocked('git_unavailable', 'trusted local Git executable is missing', root)
        self.git = os.path.abspath(binary)
        self.budget = budget
        self.reads: dict[str, list | None] = {}
        self.commit, self.state, self.index = self.snapshot()

    def snapshot(self) -> tuple[str, dict, dict[bytes, bytes]]:
        roots = self.root_identity()
        self.check_config()
        head = self.head()
        stages = self.run('ls-files', '--stage', '-z').stdout
        tree = self.run('ls-tree', '-r', '-z', '--full-tree', head).stdout
        if any(row.startswith(b'160000 ') for listing in (stages, tree) for row in listing.split(b'\0')):
            raise hub.Blocked('unsupported_target', 'target Git submodules are unsupported', self.root)
        index: dict[bytes, bytes] = {}
        for row in stages.split(b'\0'):
            if row:
                metadata, path = row.split(b'\t', 1)
                if not metadata.endswith(b' 0'):
                    raise hub.Blocked('unsupported_target', 'unmerged target index is unsupported', self.root)
                index[path] = metadata
        flags = self.run('ls-files', '-v', '-z').stdout
        if any(row and not row.startswith(b'H ') for row in flags.split(b'\0')):
            raise hub.Blocked('unsupported_target', 'target skip-worktree or assume-unchanged index is unsupported', self.root)
        status = self.run('status', '--porcelain=v1', '-z', '--untracked-files=all',
                          '--no-renames', '--ignore-submodules=all').stdout
        if roots != self.root_identity() or head != self.head():
            raise hub.Blocked('snapshot_drift', 'target identity or HEAD changed', self.root)
        return head, {'root': str(self.root), 'identity': [list(row) for row in roots], 'head': head,
                      'index_sha256': digest(stages), 'status_sha256': digest(status)}, index | {b'\0': status}

    def body(self, path: str, role: str, *, required: bool) -> dict | None:
        path = relative(path)
        candidate = self.root / path
        for parent in candidate.parents:
            if parent == self.root:
                break
            if hub.physical(parent / '.git') is not None:
                raise hub.Blocked('unsupported_target', 'selected path enters another Git checkout', parent)
        found = read_regular(candidate, hub.MAX_DOC, optional=not required)
        self.reads[path] = None if found is None else [digest(found[0]), found[1]]
        if found is None:
            return None
        data, _ = found
        self.budget.add(data, path)
        lines = decoded(data, path)
        encoded = os.fsencode(path)
        stage = self.index.get(encoded)
        statuses = [row[:2].decode('ascii') for row in self.index[b'\0'].split(b'\0') if row[3:] == encoded]
        return {'id': f'target:{path}', 'path': path, 'role': role, 'sha256': digest(data),
                'head': self.commit, 'origin': 'target working tree', 'status': statuses or ['not reported by Git status'],
                'index_entry': None if stage is None else stage.decode('ascii'),
                'ranges': [{'line': 1, 'end_line': len(lines), 'text': '\n'.join(lines)}]}

    def finish(self) -> None:
        if self.snapshot() != (self.commit, self.state, self.index):
            raise hub.Blocked('snapshot_drift', 'target HEAD/index/status drifted during inspection', self.root)
        for name, expected in self.reads.items():
            found = read_regular(self.root / name, hub.MAX_DOC, optional=True)
            if (None if found is None else [digest(found[0]), found[1]]) != expected:
                raise hub.Blocked('snapshot_drift', 'selected target bytes drifted during inspection', name)


def hub_body(snapshot: HubSnapshot, row: dict) -> dict:
    doc = snapshot.documents[row['path']]
    body = snapshot.bodies[doc.path]
    if digest(body) != row['sha256']:
        block('snapshot_drift', 'source body differs from its citation', doc.path)
    lines = decoded(body, doc.path)
    ranges = []
    refs = row['references'] if row['role'] in ('source_map', 'document_registry') else []
    fragments = [ref for ref in row['references'] if 'fragment' in ref]
    if fragments:
        start = fragments[0]['line']
        # A linked heading includes its subtree, through the next heading at the same or higher level.
        level = len(lines[start - 1].lstrip().split(None, 1)[0])
        end = next((i - 1 for i, _ in doc.headings() if i > start
                    and len(lines[i - 1].lstrip().split(None, 1)[0]) <= level), len(lines))
        refs = [{'line': start, 'end_line': end}]
    for ref in refs or [{'line': 1, 'end_line': len(lines)}]:
        start, end = ref['line'], ref.get('end_line', ref['line'])
        if not 1 <= start <= end <= len(lines):
            block('invalid_citation', 'source index range is not present in the verified body', doc.path)
        ranges.append({'line': start, 'end_line': end, 'text': '\n'.join(lines[start - 1:end])})
    return row | {'id': f'hub:{doc.path}', 'origin': 'hub clean committed checkout', 'ranges': ranges}


def selections(raw: Any) -> dict:
    row = keys(raw, set(), ('paths', 'workflow', 'change'))
    paths = [relative(item) for item in array(row.get('paths', []))]
    workflow = [relative(item) for item in array(row.get('workflow', []))]
    change = token(row['change']) if 'change' in row else None
    if change == 'archive' or len(set(paths + workflow)) != len(paths + workflow):
        block('invalid_selection', 'duplicate sources or unsupported artifact change')
    return {'paths': paths, 'workflow': workflow, 'change': change}


def artifact_paths(root: Path, change: str) -> set[str]:
    base = f'openspec/changes/{change}'
    info = hub.physical(root / base)
    if info is None:
        return set()
    if not stat.S_ISDIR(info.st_mode):
        raise hub.Blocked('unsafe_path', 'expected a physical OpenSpec change directory', base)
    result = {f'{base}/{name}' for name in ('proposal.md', 'design.md', 'tasks.md')
              if hub.physical(root / base / name) is not None}
    specs = root / base / 'specs'
    spec_dir = hub.physical(specs)
    if spec_dir is not None:
        if not stat.S_ISDIR(spec_dir.st_mode):
            raise hub.Blocked('unsafe_path', 'expected a physical OpenSpec specs directory', specs)
        with os.scandir(specs) as children:
            for index, entry in enumerate(children):
                if index >= SOURCE_MAX:
                    raise hub.Blocked('source_limit', 'too many OpenSpec spec entries', specs)
                name = relative(f'{base}/specs/{entry.name}/spec.md')
                if not entry.is_dir(follow_symlinks=False) or hub.physical(root / name) is None:
                    raise hub.Blocked('unsupported_artifacts', 'expected a physical spec directory containing spec.md', name)
                result.add(name)
    return result


def target_bodies(snapshot: TargetSnapshot, selection: dict) -> tuple[list[dict], dict]:
    names = {name: ('selected_code', True) for name in selection['paths']}
    names.update({name: ('target_workflow', True) for name in selection['workflow']})
    for name in ('AGENTS.md', 'README.md', '.agents/workspaces.json', 'openspec/config.yaml'):
        names.setdefault(name, ('target_rules', name == 'AGENTS.md'))
    names['AGENTS.md'] = ('target_rules', True)
    change = selection['change']
    artifacts = artifact_paths(snapshot.root, change) if change else set()
    for name in artifacts:
        names[name] = ('openspec_artifact', True)
    for name, (_, required) in list(names.items()):
        if required:
            for parent in PurePosixPath(name).parents:
                scoped = str(parent / 'AGENTS.md')
                names.setdefault(scoped, ('target_rules', False))
                if len(names) > SOURCE_MAX:
                    block('source_limit', 'too many selected target sources and instruction locations')
    if len(names) > SOURCE_MAX:
        block('source_limit', 'too many selected target sources and instruction locations')
    bodies = []
    for name, (role, required) in sorted(names.items()):
        found = snapshot.body(name, role, required=required)
        if found is not None:
            bodies.append(found)
    snapshot.finish()
    if change and artifact_paths(snapshot.root, change) != artifacts:
        block('snapshot_drift', 'OpenSpec artifact inventory changed during inspection')
    roles = {PurePosixPath(name).name for name in artifacts}
    return bodies, {'change': change, 'sources': [f'target:{name}' for name in sorted(artifacts)],
                    'standard_set_present': {'proposal.md', 'tasks.md', 'spec.md'} <= roles}


def citation(raw: Any, sources: dict[str, dict]) -> dict:
    row = keys(raw, {'source', 'sha256', 'line', 'end_line'})
    name = text(row['source'], 600)
    sha = token(row['sha256'], HASH)
    start, end = row['line'], row['end_line']
    source = sources.get(name)
    if source is not None and sha == source['sha256'] and type(start) is int and type(end) is int:
        for span in source['ranges']:
            if span['line'] <= start <= end <= span['end_line']:
                # The current context includes the complete range. Stored notes deliberately keep only a bounded excerpt.
                excerpt = '\n'.join(span['text'].split('\n')[start - span['line']:end - span['line'] + 1])
                return dict(row, excerpt=excerpt[:1200], excerpt_shortened=len(excerpt) > 1200)
    raise hub.Blocked('invalid_citation', 'review citation must name a current body hash and displayed line range')


def ref_list(raw: Any, sources: dict[str, dict]) -> list[dict]:
    return [citation(item, sources) for item in array(raw, 64)]


def bullets(raw: Any) -> list[str]:
    return [text(item, 800) for item in array(raw, 32)]


def decision_rows(raw: Any, sources: dict[str, dict]) -> dict:
    result: dict[str, dict] = {}
    for key, item in mapping(raw).items():
        row = keys(item, {'state', 'owner', 'citations'}, ('value', 'question', 'answer'))
        state, owner = row['state'], text(row['owner'], 160)
        cites = ref_list(row['citations'], sources)
        if not cites:
            block('invalid_review', 'each structured decision needs a source basis')
        decided = {'state': state, 'owner': owner, 'citations': cites}
        if state == 'settled' and not {'question', 'answer'}.intersection(row):
            result[key] = decided | {'value': text(row.get('value'))}
        elif state == 'open' and 'value' not in row:
            question = text(row.get('question'), 500)
            result[key] = decided | {'question': question}
            if 'answer' in row:
                answer = keys(row['answer'], {'by', 'role', 'text'})
                claimed = text(answer['role'], 160)
                result[key]['answer'] = {'by': text(answer['by'], 160), 'role': claimed, 'text': text(answer['text'])}
                if owner == 'developer' and claimed == 'developer':
                    result[key]['state'] = 'answered'
                else:
                    result[key]['answer_not_applied'] = 'A developer answer does not close an owner-blocked decision; supply current owner source evidence.'
        else:
            block('invalid_review', 'expected a settled source fact or an open decision with an attributed answer')
    return result


def scope_rows(raw: Any, decisions: dict, sources: dict[str, dict]) -> dict:
    scopes = {}
    for key, item in mapping(raw).items():
        row = keys(item, {'summary', 'acceptance', 'decisions', 'citations'}, ('independence',))
        dependencies = [token(dep) for dep in array(row['decisions'])]
        acceptance, cites = bullets(row['acceptance']), ref_list(row['citations'], sources)
        if not acceptance or not cites or set(dependencies) - decisions.keys():
            block('invalid_review', 'scopes need acceptance, current sources and declared decision keys')
        scopes[key] = {'summary': text(row['summary']), 'acceptance': acceptance, 'decisions': dependencies, 'citations': cites}
        if 'independence' in row:
            scopes[key]['independence'] = text(row['independence'])
    if 'full' not in scopes or set(scopes['full']['decisions']) != decisions.keys():
        block('invalid_review', 'the full scope must account for every structured decision')
    return scopes


def source_gaps(raw: Any, scopes: dict) -> dict:
    gaps = {}
    for key, item in mapping(raw).items():
        row = keys(item, {'reason', 'scopes'})
        applies = [token(value) for value in array(row['scopes'])]
        if set(applies) - scopes.keys() or (applies and 'full' not in applies):
            block('invalid_review', 'a material source gap must include the full scope and only declared slices')
        gaps[key] = {'reason': text(row['reason']), 'scopes': applies}
    return gaps


def artifact_basis(raw: Any, sources: dict[str, dict], artifacts: dict, active_scope: str,
                   scope_citations: list[dict]) -> dict:
    if raw is None:
        return {'current': False, 'reason': 'Missing current attributed artifact review and validation evidence.'}
    row = keys(raw, {'change', 'scope', 'reviewed_by', 'validation_by', 'observed_at', 'validation', 'result', 'citations'})
    change = token(row['change'])
    cites = ref_list(row['citations'], sources)
    cited = {ref['source'] for ref in cites}
    # Evidence must cover every current artifact body, not just an index, path or a heading.
    complete = all(any(ref['source'] == name and ref['line'] == span['line'] and ref['end_line'] == span['end_line']
                       for ref in cites) for name in artifacts['sources'] for span in sources[name]['ranges'])
    if row['result'] not in ('passed', 'failed', 'not_observed'):
        block('invalid_review', 'declare the attributed validation result')
    workflow = sorted({ref['source'] for ref in scope_citations if sources[ref['source']]['role'] == 'target_workflow'})
    details = {'current': False, 'change': change, 'scope': token(row['scope']), 'result': row['result'],
               'target_workflow_citations': workflow,
               'reviewed_by': text(row['reviewed_by'], 160), 'validation_by': text(row['validation_by'], 160),
               'observed_at': input_time(row['observed_at']), 'validation': text(row['validation']), 'citations': cites,
               'limits': 'Attributed review and validation evidence only; not authenticated or rerun by this helper.'}
    if (change != artifacts['change'] or details['scope'] != active_scope or details['result'] != 'passed'
            or not artifacts['standard_set_present'] or cited != set(artifacts['sources']) or not complete or not workflow):
        return details | {'reason': 'No complete current artifact-body review basis for the selected change.'}
    return details | {'current': True}


def assess(packet: Any, context_hash: str, bodies: list[dict], artifacts: dict, blockers: list[dict],
           binding: dict) -> dict:
    base: dict = {'state': 'blocked', 'active_question': None, 'decisions': {}, 'open_owner_questions': [], 'exclusions': [],
                  'next_step': 'Reinspect the missing or changed sources; do not act on an incomplete assessment.',
                  'blockers': list(blockers), 'launch_authority': False, 'limits': REVIEW_LIMIT}
    if binding['binding'] is None:
        if packet is not None:
            block('invalid_review', 'resolve the selected association before supplying a source review')
        base['active_question'] = {'key': 'prd-association', 'owner': 'developer',
                                   'text': 'Which PRD000 is explicitly associated with this selected task?'}
        base['next_step'] = 'Ask the one PRD association question; do not look up a guessed PRD.'
        return base
    if packet is None:
        if not blockers:
            base['next_step'] = 'Read the displayed sources and author a source-backed clarification packet.'
            base['blockers'].append({'code': 'review_missing', 'detail': 'No structured source review supplied.'})
        return base
    row = keys(packet, {'context_digest', 'by', 'decisions', 'scopes'},
               ('assumptions', 'exclusions', 'source_gaps', 'scope_approval', 'artifact_review'))
    if token(row['context_digest'], HASH) != context_hash:
        base['blockers'].append({'code': 'stale_review', 'detail': 'Review packet is not bound to the current context.'})
        return base
    sources = {doc['id']: doc for doc in bodies}
    decisions = decision_rows(row['decisions'], sources)
    scopes = scope_rows(row['scopes'], decisions, sources)
    gaps = source_gaps(row.get('source_gaps', {}), scopes)
    active = 'full'
    approval = None
    if (raw := row.get('scope_approval')) is not None:
        supplied = keys(raw, {'scope', 'by', 'status'})
        scope_id = token(supplied['scope'])
        status = supplied['status']
        approval = {'scope': scope_id, 'by': text(supplied['by'], 160), 'status': status,
                    'from': 'developer-supplied scope decision; not authenticated or launch authority'}
        if scope_id == 'full' or not scopes.get(scope_id, {}).get('independence') or status not in ('approved', 'refused'):
            block('invalid_review', 'narrowed scope must be an explicitly justified, acknowledged slice')
        if status == 'approved':
            active = scope_id
    proof = artifact_basis(row.get('artifact_review'), sources, artifacts, active, scopes[active]['citations'])
    per_scope: dict[str, dict] = {}
    for key, scope in scopes.items():
        issues = [decision for decision in scope['decisions'] if decisions[decision]['state'] == 'open']
        needed = [gap for gap, data in gaps.items() if key in data['scopes']]
        per_scope[key] = scope | {'open_decisions': issues, 'missing_sources': needed,
                                  'state': 'blocked' if issues or needed or blockers else 'clarified'}
    base.update(reviewed_by=text(row['by'], 160), decisions=decisions, scopes=per_scope, active_scope=active,
                source_gaps=gaps, assumptions=bullets(row.get('assumptions', [])), scope_approval=approval,
                exclusions=bullets(row.get('exclusions', [])), excluded_scopes=[] if active == 'full' else sorted(
                    name for name in scopes if name not in ('full', active)),
                open_owner_questions=[{'key': key, 'owner': item['owner'], 'text': item['question']}
                                      for key, item in decisions.items() if item['state'] == 'open' and item['owner'] != 'developer'])
    chosen = per_scope[active]
    base['blockers'] += ([{'code': 'decision_open', 'key': key, 'owner': decisions[key]['owner']} for key in chosen['open_decisions']]
                         + [{'code': 'missing_dependent_source', 'key': key} for key in chosen['missing_sources']])
    if blockers:
        return base
    if base['blockers']:
        for key in chosen['open_decisions']:
            if decisions[key]['owner'] == 'developer':
                base['active_question'] = {'key': key, 'owner': 'developer', 'text': decisions[key]['question']}
                base['next_step'] = 'Ask the one active developer question and await an attributed answer.'
                return base
        base['next_step'] = 'Wait for the named source/decision owner; review any independent slice separately.'
        return base
    base['artifact_evidence'] = proof
    if proof['current']:
        base['state'] = 'ready_for_implementation'
        base['next_step'] = 'Review the requirements-level recommendation with the developer; keep the existing artifacts. Stop before launch.'
    else:
        base['state'] = 'ready_for_drafting'
        base['next_step'] = ('Offer approval to review or revise the selected existing artifacts; do not duplicate them.'
                             if artifacts['sources'] else 'Offer OpenSpec drafting approval; do not draft or launch.')
    return base


def summarize(doc: dict) -> dict:
    return doc | {'ranges': [{key: span[key] for key in ('line', 'end_line')} for span in doc['ranges']]}


def selection_input(raw: Any, native: str) -> tuple[dict, Any, Any]:
    if raw is None:
        return selections({}), None, None
    row = keys(raw, {'version', 'task'}, ('association', 'select', 'review'))
    if type(row['version']) is not int or row['version'] != 1 or token(row['task'], NATIVE) != native:
        block('wrong_task', 'packet must name the selected native task')
    return selections(row.get('select', {})), row.get('association'), row.get('review')


def input_time(value: Any) -> str:
    when = text(value, 40)
    parsed = datetime.fromisoformat(when)
    if parsed.tzinfo is None or parsed.isoformat() != when:
        block('invalid_plan', 'expected the timestamp shown by inspect')
    return when


def inspect_task(workspace: Path, alias: str, intake: Path, packet: Any, when: str,
                 *, load_history: bool = True) -> dict:
    excluded, target, workspace_state_before = workspace_context(workspace, alias)
    if intake.suffix != '.json' or any(intake.is_relative_to(root) for root in excluded if root != workspace):
        raise hub.Blocked('unsafe_input', 'keep B1 intake JSON separate from the kit and source repositories', intake)
    pair = read_regular(intake, INTAKE_MAX)
    assert pair is not None
    data, stamp = pair
    imported, candidates = intake_view(data, intake)
    native = imported['selected']['id']
    selection, supplied_prd, review = selection_input(packet, native)
    binding = association(candidates, supplied_prd)
    blockers = []
    if binding['binding'] is None:
        blockers.append({'code': 'association_conflict' if binding['conflict'] else 'association_missing',
                         'detail': 'No automatic source lookup without one explicit binding.'})
    if imported['status'] != 'observed' or imported['unresolved']:
        blockers.append({'code': 'b1_incomplete', 'detail': 'Imported task/ancestor/comment evidence is incomplete; do not settle dependent claims.'})
    budget = TextBudget()
    bodies: list[dict] = []
    source_state = None
    target_state = None
    artifacts: dict = {'change': selection['change'], 'sources': [], 'standard_set_present': False}
    map_path = workspace / hub.MAPPING
    mapping_pair = None
    snapshot = None
    target_snapshot = None
    if binding['binding'] is not None:
        try:
            mapping_pair = read_regular(map_path, REVIEW_MAX)
            assert mapping_pair is not None
            source = hub.parse_mapping(mapping_pair[0], map_path)
            if intake.is_relative_to(source):
                block('unsafe_input', 'B1 intake cannot reside in the mapped source repository')
            snapshot = HubSnapshot(source, excluded, budget)
            prd = binding['binding']['prd']
            binding['lookup'].append(prd)
            lookup = hub.source_index(snapshot, prd)
            bodies.extend(hub_body(snapshot, row) for row in lookup['documents'])
            source_state = {'root': str(source), 'commit': snapshot.commit,
                            'identity': [list(row) for row in snapshot.identity], 'mapping_sha256': digest(mapping_pair[0])}
        except hub.Blocked as error:
            blockers.append(error.diagnostic)
            bodies = []
        except OSError:
            blockers.append({'code': 'source_unreadable', 'detail': 'Required hub evidence could not be read.'})
            bodies = []
        try:
            target_snapshot = TargetSnapshot(target, budget)
            target_docs, artifacts = target_bodies(target_snapshot, selection)
            bodies.extend(target_docs)
            target_state = target_snapshot.state
        except hub.Blocked as error:
            blockers.append(error.diagnostic)
        except OSError:
            blockers.append({'code': 'source_unreadable', 'detail': 'Required target evidence could not be read.'})
    if snapshot is not None and source_state is not None:
        try:
            snapshot.finish()
        except (hub.Blocked, OSError):
            blockers.append({'code': 'snapshot_drift', 'detail': 'Source checkout drifted after body capture.'})
            bodies = [doc for doc in bodies if not doc['id'].startswith('hub:')]
            source_state = None
    try:
        current_map = read_regular(map_path, REVIEW_MAX, optional=True) if mapping_pair is not None else None
        if (read_regular(intake, INTAKE_MAX) != pair or workspace_context(workspace, alias)[2] != workspace_state_before
                or current_map != mapping_pair):
            block('snapshot_drift', 'workspace, mappings or B1 intake changed during inspection')
    except OSError as error:
        raise hub.Blocked('snapshot_drift', 'workspace, mappings or B1 intake became unreadable') from error
    if target_snapshot is not None and target_state is not None:
        try:
            target_snapshot.finish()
            if selection['change'] and {f'target:{p}' for p in artifact_paths(target, selection['change'])} != set(artifacts['sources']):
                block('snapshot_drift', 'OpenSpec sources changed after body capture')
        except (hub.Blocked, OSError):
            blockers.append({'code': 'snapshot_drift', 'detail': 'Target drifted after body capture.'})
            bodies = [doc for doc in bodies if not doc['id'].startswith('target:')]
            target_state = None
            artifacts = {'change': selection['change'], 'sources': [], 'standard_set_present': False}
    source_summary = [summarize(body) for body in bodies]
    imported_data = {'path': str(intake), 'sha256': digest(data), 'file_identity': stamp,
                     'service_freshness': 'Not observed here; original service metadata is imported, not refreshed.'}
    bound = {'task': native, 'repository': alias, 'target_root': str(target), 'association': binding,
             'workspace_state': workspace_state_before, 'hub': source_state, 'target': target_state, 'sources': source_summary,
             'artifacts': artifacts, 'intake': imported_data, 'selection': selection, 'blockers': blockers}
    context_hash = digest(json_bytes(bound))
    assessment = assess(review, context_hash, bodies, artifacts, blockers, binding)
    latest = history(workspace, alias, native) if load_history else None
    if latest is not None and latest['record']['target_root'] != str(target):
        block('record_conflict', 'the existing task lineage is bound to a different target mapping')
    observations = [{'task_id': item['id'], 'observation': item['observation']} for item in
                    [imported['selected'], *imported['ancestors']]]
    record = {'task': native, 'repository': alias, 'target_root': str(target), 'context_digest': context_hash,
              'intake': imported_data | {'imported_at': when, 'observations': observations, 'unresolved': imported['unresolved']},
              'hub': source_state, 'target': target_state, 'association': binding, 'sources': source_summary,
              'artifacts': artifacts, 'assessment': assessment,
              'related_context': {'shared_meeting_notes': 'not established; no location or owner inferred',
                                  'personal_fathom': 'optional; not accessed'}}
    plan = {'version': 1, 'workspace': str(workspace), 'repository': alias, 'task': native, 'intake': str(intake),
            'imported_at': when, 'packet': packet, 'parent': None if latest is None else latest['revision'], 'record': record}
    if len(json_bytes(plan)) > RECORD_MAX:
        block('record_limit', 'private plan exceeds its size bound; narrow the selected review evidence')
    return {'authority': AUTHORITY, 'launch_authority': False, 'plan': plan,
            'context': {'digest': context_hash, 'intake': imported, 'sources': bodies}}


def private_dir(path: Path, info: os.stat_result) -> None:
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
        raise hub.Blocked('unsafe_record_path', 'expected an owner-only 0700 task directory', path)


def history(workspace: Path, alias: str, task: str) -> dict | None:
    token(alias)
    token(task, NATIVE)
    directory = workspace / '.dcc/tasks'
    for path in (directory, directory / alias, directory / alias / task):
        info = hub.physical(path)
        if info is None:
            return None
        private_dir(path, info)
    directory = directory / alias / task
    names: list[str] = []
    with os.scandir(directory) as children:
        for entry in children:
            if len(names) == 128 or not REVISION.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
                raise hub.Blocked('record_conflict', 'unexpected record entry or history limit reached; no file was replaced', directory)
            names.append(entry.name)
    latest = None
    parent = None
    root = None
    size = 0
    for number, name in enumerate(sorted(names), 1):
        path = directory / name
        found = read_regular(path, RECORD_MAX)
        assert found is not None
        data, (_, _, mode, *_rest) = found
        info = path.lstat()
        if stat.S_IMODE(mode) != 0o600 or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise hub.Blocked('unsafe_record_path', 'expected a private, unlinked-to-elsewhere 0600 revision', path)
        size += len(data)
        if size > TOTAL_MAX:
            block('record_limit', 'task history exceeds its aggregate read bound', directory)
        row = json_object(data, path)
        latest = keys(row, {'version', 'workspace', 'repository', 'task', 'sequence', 'parent', 'intake', 'packet', 'record'})
        record = keys(row['record'], {'task', 'repository', 'target_root', 'context_digest', 'intake', 'hub', 'target',
                                     'association', 'sources', 'artifacts', 'assessment', 'related_context'})
        ident = f'{number:06d}-{digest(data)}.json'
        if (type(row['version']) is not int or row['version'] != 1 or type(row['sequence']) is not int
                or row['sequence'] != number or row['parent'] != parent or name != ident or row['workspace'] != str(workspace)
                or row['repository'] != alias or record['repository'] != alias or row['task'] != task or record['task'] != task
                or not isinstance(record['target_root'], str) or (root is not None and record['target_root'] != root)
                or not isinstance(record['assessment'], dict) or record['assessment'].get('launch_authority') is not False
                or not isinstance(record['intake'], dict) or record['intake'].get('path') != row['intake']):
            raise hub.Blocked('record_conflict', 'malformed revision, wrong task/repo identity or broken ancestry', path)
        input_time(record['intake'].get('imported_at'))
        local_path(row['intake'])
        token(record['context_digest'], HASH)
        selection_input(row['packet'], task)
        root = record['target_root']
        parent = ident
        latest['revision'] = ident
    return latest


@contextmanager
def task_directory(workspace: Path, alias: str, task: str) -> Iterator[int]:
    # Descend using directory descriptors. A symlink cannot redirect a record write.
    directory_flag = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(workspace.anchor, directory_flag)
    try:
        path = Path(workspace.anchor)
        for part in (*workspace.parts[1:], '.dcc', 'tasks', alias, task):
            path /= part
            private = path.is_relative_to(workspace / '.dcc/tasks')
            try:
                new = os.open(part, directory_flag, dir_fd=fd)
            except FileNotFoundError:
                if not private:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                new = os.open(part, directory_flag, dir_fd=fd)
            os.close(fd)
            fd = new
            if private:
                private_dir(path, os.fstat(fd))
        yield fd
    finally:
        os.close(fd)


def load_plan(path: Path) -> dict:
    found = read_regular(path, RECORD_MAX + 1024)
    assert found is not None
    result = json_object(found[0], path).get('plan')
    if not isinstance(result, dict) or len(json_bytes(result)) > RECORD_MAX:
        block('invalid_plan', 'expected the bounded plan displayed by inspect', path)
    return result


def save(plan: dict) -> dict:
    row = keys(plan, {'version', 'workspace', 'repository', 'task', 'intake', 'imported_at', 'packet', 'parent', 'record'})
    if type(row['version']) is not int or row['version'] != 1:
        block('invalid_plan', 'expected version 1 displayed plan')
    workspace, alias = local_path(row['workspace']), token(row['repository'])
    task, intake = token(row['task'], NATIVE), local_path(row['intake'])
    current = inspect_task(workspace, alias, intake, row['packet'], input_time(row['imported_at']))['plan']
    if json_bytes(current) != json_bytes(plan):
        block('stale_plan', 'the displayed plan or prior revision changed; inspect again')
    assessment = current['record']['assessment']
    if any(item['code'] == 'stale_review' for item in assessment['blockers']):
        block('stale_review', 'review packet must bind the current source context before it can be stored')
    newest = history(workspace, alias, task)
    if (None if newest is None else newest['revision']) != current['parent']:
        block('stale_plan', 'record history changed; inspect again')
    sequence = 1 if newest is None else newest['sequence'] + 1
    if sequence > 128:
        block('record_limit', 'task lineage reached its revision limit')
    row = {name: current[name] for name in ('version', 'workspace', 'repository', 'task', 'intake', 'packet', 'parent', 'record')}
    data = json_bytes(row | {'sequence': sequence})
    if len(data) > RECORD_MAX:
        block('record_limit', 'private revision exceeds its size bound')
    revision = f'{sequence:06d}-{digest(data)}.json'
    with task_directory(workspace, alias, task) as fd:
        # Check the opened directory, then reserve a filename without replacing anything.
        listing = os.listdir(fd)
        if len(listing) != sequence - 1 or (current['parent'] is not None and current['parent'] not in listing):
            block('record_conflict', 'record history changed before exclusive creation')
        try:
            child = os.open(revision, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        except OSError as error:
            if error.errno in (errno.EEXIST, errno.ELOOP):
                raise hub.Blocked('record_conflict', 'revision already exists; no file was replaced') from error
            raise
        with os.fdopen(child, 'wb') as stream:
            stream.write(data)
    return {'revision': revision, 'parent': row['parent'], 'path': f'.dcc/tasks/{alias}/{task}/{revision}',
            'record': row['record'], 'launch_authority': False, 'authority': AUTHORITY}


def resume(workspace: Path, alias: str, task: str) -> dict:
    latest = history(workspace, alias, task)
    if latest is None:
        block('missing_record', 'no saved revision for the selected task and repository')
    record = latest['record']
    old = record['assessment']
    diagnostics = []
    try:
        current = inspect_task(workspace, alias, local_path(latest['intake']), latest['packet'],
                               record['intake']['imported_at'], load_history=False)['plan']['record']
        if current['task'] != task or current['context_digest'] != record['context_digest']:
            for field in ('intake', 'hub', 'target', 'target_root', 'association', 'sources', 'artifacts'):
                if current[field] != record[field]:
                    diagnostics.append(f'{field} changed')
            if not diagnostics:
                diagnostics.append('workspace fingerprints or required source availability changed')
    except hub.Blocked as error:
        diagnostics.append(f"Recheck blocked: {error.diagnostic['code']}")
    except (OSError, ValueError, TypeError):
        diagnostics.append('Current inputs unavailable or malformed')
    if diagnostics:
        assessment = old | {'state': 'blocked', 'active_question': None, 'launch_authority': False,
                            'next_step': 'Reinspect current inputs and review again; historical decisions are preserved, not re-approved.',
                            'blockers': [{'code': 'snapshot_drift', 'detail': item} for item in diagnostics] + old['blockers']}
    else:
        # Current shape/basis must pass again even if saved status fields disagree.
        assessment = current['assessment']
    return {'revision': latest['revision'], 'parent': latest['parent'], 'historical_record': record,
            'assessment': assessment, 'drift': diagnostics, 'launch_authority': False, 'authority': AUTHORITY}
