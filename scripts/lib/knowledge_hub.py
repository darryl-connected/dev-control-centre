"""Read-only snapshot and bounded source navigation for one local knowledge hub."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

HUB = 'knowledge-hub'
SOURCE_MAP = f'{HUB}/prds/source-map.md'
REGISTRY = f'{HUB}/index.md'
ARCH = f'{HUB}/architecture'
ARCH_GUIDE = f'{ARCH}/README.md'
MAPPING = '.dcc/knowledge.json'
MAP_HEADER = ('ID and area', 'Organization PRD in this checkout', 'Working context', 'What the local evidence says')
REGISTRY_HEADER = ('Category', 'Document Name', 'Status', 'Owner', 'Last Updated', 'Link')
GUIDES = (
    ('repository_rules', 'AGENTS.md'), ('repository_navigation', 'README.md'),
    ('hub_rules', f'{HUB}/AGENTS.md'), ('hub_navigation', f'{HUB}/README.md'),
    ('hub_change_history', f'{HUB}/CHANGELOG.md'), ('prd_protection', f'{HUB}/prds/active/AGENTS.md'),
    ('architecture_navigation', ARCH_GUIDE),
)
COMPANIONS = {'api-contracts.md': 'active_api_contracts', 'data-schema.md': 'active_data_schema',
              'diagrams.md': 'active_diagrams', 'CHANGELOG.md': 'active_change_history',
              'future-improvements.md': 'active_future_improvements'}
PRD = re.compile(r'PRD[0-9]{3}')
OBJECT_ID = re.compile(rb'(?:[a-f0-9]{40}|[a-f0-9]{64})')
LINK = re.compile(r'\[[^\[\]\\\n]+\]\((?:<([^<>\n]+)>|([^()\s<>]+))\)')
HEADING = re.compile(r'^ {0,3}#{1,6}[ \t]+(.+?)\s*#*\s*$')
MAX_DOC = 4 * 1024 * 1024


class Blocked(ValueError):
    def __init__(self, code: str, detail: str, path: str | Path | None = None, line: int | None = None):
        super().__init__(detail)
        self.diagnostic: dict = {'code': code, 'detail': detail}
        if path is not None:
            self.diagnostic['path'] = str(path)
        if line is not None:
            self.diagnostic['line'] = line


def overlap(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def physical(path: Path) -> os.stat_result | None:
    """Do not follow an existing link, including a broken ancestor or leaf."""
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or (component != path and not stat.S_ISDIR(info.st_mode)):
            raise Blocked('unsafe_path', 'expected physical path components without symlinks', component)
    return info


def regular_bytes(path: Path, *, optional: bool = False) -> bytes | None:
    info = physical(path)
    if info is None and optional:
        return None
    if info is None:
        raise Blocked('missing_file', 'required local file is absent', path)
    if not stat.S_ISREG(info.st_mode):
        raise Blocked('unsafe_path', 'expected a regular file', path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise Blocked('unsafe_path', 'expected a regular file', path)
        data = stream.read(MAX_DOC + 1)
    if len(data) > MAX_DOC:
        raise Blocked('size_limit', 'local file exceeds the adapter limit', path)
    return data


def parse_mapping(data: bytes, path: Path) -> Path:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=unique)
        if (not isinstance(value, dict) or set(value) != {'version', 'checkout'}
                or type(value['version']) is not int or value['version'] != 1):
            raise ValueError('mapping schema')
        root = value['checkout']
        if (not isinstance(root, str) or not Path(root).is_absolute() or '..' in Path(root).parts
                or str(Path(root)) != root or any(ord(char) < 32 for char in root)):
            raise ValueError('checkout path')
    except (ValueError, RecursionError) as error:
        raise Blocked('invalid_mapping', 'expected version 1 and one absolute physical checkout path', path) from error
    return Path(root)


def mapping_root(workspace: Path) -> Path | None:
    path = workspace / MAPPING
    data = regular_bytes(path, optional=True)
    return None if data is None else parse_mapping(data, path)


class Snapshot:
    """One observed commit; compare selected blobs with working bytes and recheck at the end."""

    def __init__(self, root: Path, excluded: tuple[Path, ...]):
        self.root = root
        if any(overlap(root, path) for path in excluded):
            raise Blocked('checkout_overlap', 'source checkout must be separate from kit, workspace and mapped targets', root)
        git = shutil.which('git')
        if git is None:
            raise Blocked('git_unavailable', 'trusted local Git executable is missing', root)
        self.git = os.path.abspath(git)
        self.identity = self.root_identity()
        self.check_config()
        self.commit = self.head()
        self.clean()
        if self.head() != self.commit or self.root_identity() != self.identity:
            raise Blocked('snapshot_drift', 'checkout identity or HEAD changed during inspection', root)
        self.tree: dict[str, tuple[str, str]] = {}
        self.documents: dict[str, Document] = {}

    def root_identity(self) -> tuple[tuple[int, int, int], ...]:
        identities = []
        for path in (self.root, self.root / '.git'):
            info = physical(path)
            if info is None or not stat.S_ISDIR(info.st_mode):
                raise Blocked('checkout_unavailable', 'expected a physical Git checkout root with its own .git directory', path)
            identities.append((info.st_dev, info.st_ino, info.st_mode))
        for relative in ('.git/config', '.git/HEAD', '.git/index', '.git/info/attributes', '.git/info/exclude'):
            info = physical(self.root / relative)
            if info is not None and not stat.S_ISREG(info.st_mode):
                raise Blocked('unsafe_path', 'expected regular Git metadata', self.root / relative)
        if physical(self.root / '.git/objects/info/alternates') is not None:
            raise Blocked('unsafe_git_config', 'Git object alternates are unsupported', self.root)
        return tuple(identities)

    def run(self, *args: str, accepted: tuple[int, ...] = (0,), repository: bool = True) -> subprocess.CompletedProcess[bytes]:
        env = {key: os.environ[key] for key in ('PATH', 'TMPDIR', 'SYSTEMROOT') if key in os.environ}
        env.update(LC_ALL='C', PI_OFFLINE='1', GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1',
                   GIT_ALLOW_PROTOCOL='', GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1',
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM='1', GIT_NO_REPLACE_OBJECTS='1')
        argv = [self.git, '--no-optional-locks']
        if repository:
            argv.extend(('-C', str(self.root), '-c', 'core.fsmonitor=false', '-c', 'core.attributesFile=' + os.devnull,
                         '-c', 'core.excludesFile=' + os.devnull, '-c', 'core.hooksPath=' + os.devnull))
        else:
            # Config discovery on entering the source repo can expand includes before the
            # config subcommand sees --no-includes. Read the explicit file outside that repo.
            argv.extend(('-C', self.root.anchor))
        argv.extend(args)
        try:
            child = subprocess.run(argv, env=env, capture_output=True, check=False, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Blocked('git_unavailable', f'local Git {args[0]} could not be observed', self.root) from error
        if child.returncode not in accepted:
            # Do not relay arbitrary source config, credentials, program output or source bodies.
            raise Blocked('git_read_failed', f'local Git {args[0]} failed', self.root)
        return child

    def check_config(self) -> None:
        # This precheck deliberately does not expand includes. Do not inspect config values.
        blocked = r'^(include\.|includeif\.|filter\..*\.(process|clean)$|core\.worktree$|extensions\.worktreeconfig$)'
        if self.run('config', '--file', str(self.root / '.git/config'), '--no-includes', '--name-only',
                    '--get-regexp', blocked, accepted=(0, 1), repository=False).returncode == 0:
            raise Blocked('unsafe_git_config', 'includes, checkout redirects, worktree config or executable clean filters are unsupported', self.root)
        top = self.run('rev-parse', '--show-toplevel').stdout.removesuffix(b'\n')
        if os.fsencode(self.root) != top:
            raise Blocked('checkout_unavailable', 'supply the exact physical Git root', self.root)

    def head(self) -> str:
        raw = self.run('rev-parse', '--verify', 'HEAD^{commit}').stdout.strip()
        if not OBJECT_ID.fullmatch(raw):
            raise Blocked('git_read_failed', 'could not establish exactly one HEAD commit', self.root)
        return raw.decode('ascii')

    def clean(self) -> None:
        flags = self.run('ls-files', '-v', '-z').stdout.split(b'\0')
        if any(row and not row.startswith(b'H ') for row in flags):
            raise Blocked('dirty_checkout', 'unmerged, assume-unchanged or skip-worktree index entries are unsupported', self.root)
        # Check the staged gitlink too, but never recurse into a submodule checkout.
        index = self.run('diff-index', '--cached', '--quiet', '--no-ext-diff', '--no-textconv',
                         '--ignore-submodules=none', self.commit, '--', accepted=(0, 1))
        status = self.run('status', '--porcelain=v1', '-z', '--untracked-files=all',
                          '--no-renames', '--ignore-submodules=all')
        if index.returncode or status.stdout:
            raise Blocked('dirty_checkout', 'source checkout has staged, unstaged or untracked changes', self.root)

    def inventory(self) -> None:
        raw = self.run('ls-tree', '-r', '-t', '-z', '--full-tree', self.commit).stdout
        for entry in raw.split(b'\0'):
            if entry:
                metadata, path = entry.split(b'\t', 1)
                mode, _, oid = metadata.decode('ascii').split()
                self.tree[os.fsdecode(path)] = (mode, oid)

    def working_bytes(self, path: str) -> bytes:
        data = regular_bytes(self.root / path)
        assert data is not None
        if not data:
            raise Blocked('unsupported_document', 'empty selected Markdown document', path)
        return data

    def document(self, path: str) -> Document:
        if path in self.documents:
            return self.documents[path]
        ancestors = (str(parent) for parent in PurePosixPath(path).parents if str(parent) != '.')
        if any(self.tree.get(parent, ('', ''))[0] in ('120000', '160000') for parent in ancestors):
            raise Blocked('unsafe_path', 'selected path traverses a committed symlink or gitlink', path)
        entry = self.tree.get(path)
        if entry is None:
            raise Blocked('missing_source', 'selected path is absent at the observed commit; no replacement selected', path)
        mode, oid = entry
        if mode not in ('100644', '100755'):
            raise Blocked('unsafe_path', 'selected source is not a regular committed file (symlinks and gitlinks are not followed)', path)
        working = self.working_bytes(path)
        size = int(self.run('cat-file', '-s', oid).stdout)
        if size > MAX_DOC:
            raise Blocked('size_limit', 'selected blob exceeds the adapter limit', path)
        blob = self.run('cat-file', 'blob', oid).stdout
        if working != blob:
            raise Blocked('snapshot_drift', 'selected working bytes do not match the observed commit', path)
        try:
            doc = Document(path, hashlib.sha256(blob).hexdigest(), blob.decode('utf-8-sig').splitlines())
        except UnicodeError as error:
            raise Blocked('unsupported_document', 'expected UTF-8 Markdown', path) from error
        self.documents[path] = doc
        return doc

    def finish(self) -> None:
        if self.root_identity() != self.identity or self.head() != self.commit:
            raise Blocked('snapshot_drift', 'checkout identity or HEAD changed during lookup', self.root)
        self.check_config()
        for path, doc in self.documents.items():
            try:
                current = self.working_bytes(path)
            except (OSError, Blocked) as error:
                raise Blocked('snapshot_drift', 'selected file became unavailable during lookup', path) from error
            if hashlib.sha256(current).hexdigest() != doc.sha256:
                raise Blocked('snapshot_drift', 'selected bytes changed during lookup', path)
        self.clean()
        if self.head() != self.commit or self.root_identity() != self.identity:
            raise Blocked('snapshot_drift', 'checkout identity or HEAD changed during lookup', self.root)


def readiness(workspace: Path, excluded: tuple[Path, ...]) -> str:
    try:
        root = mapping_root(workspace)
        if root is None:
            return 'not configured; optional'
        Snapshot(root, (*excluded, workspace))
        return 'locally mapped; clean checkout observed; no source lookup observed'
    except Blocked as error:
        return f"blocked: {error.diagnostic['code']}; {error}"
    except (OSError, ValueError, RuntimeError):
        return 'blocked: local mapping or checkout could not be read'


@dataclass(frozen=True)
class Document:
    path: str
    sha256: str
    lines: list[str]

    def headings(self) -> list[tuple[int, str]]:
        found = []
        fence: tuple[str, int] | None = None
        for number, text in enumerate(self.lines, 1):
            marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', text)
            if marker:
                run, tail = marker.groups()
                if fence is None:
                    fence = (run[0], len(run))
                elif fence[0] == run[0] and len(run) >= fence[1] and not tail.strip():
                    fence = None
                continue
            heading = HEADING.match(text)
            if fence is None and heading:
                found.append((number, heading[1]))
        return found

    def reference(self, fragment: str = '') -> dict:
        headings = self.headings()
        if fragment:
            headings = [(line, name) for line, name in headings if heading_slug(name) == fragment]
            if len(headings) != 1:
                raise Blocked('unsupported_fragment', 'expected exactly one matching simple Markdown heading anchor', self.path)
        if headings:
            line, name = headings[0]
            return {'line': line, 'section': name[:240], **({'fragment': fragment} if fragment else {})}
        return {'line': 1, 'end_line': max(1, len(self.lines))}

    def status(self) -> list[dict]:
        if self.lines and self.lines[0] == '---':
            for line, text in enumerate(self.lines[1:], 2):
                if text == '---':
                    break
                match = re.fullmatch(r'status:[ \t]+([A-Za-z][A-Za-z0-9 _-]{0,79})[ \t]*', text)
                if match:
                    return [{'text': match[1].strip(), 'path': self.path, 'line': line, 'from': 'frontmatter'}]
        return []


def heading_slug(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name.casefold()).strip().replace(' ', '-')


@dataclass(frozen=True)
class Link:
    path: str
    fragment: str


def local_link(target: str, document: str, line: int) -> Link:
    path, _, fragment = target.partition('#')
    try:
        if re.search(r'%(?![a-fA-F0-9]{2})', target):
            raise ValueError('invalid escape')
        path = unquote(path, errors='strict')
        fragment = unquote(fragment, errors='strict')
    except ValueError as error:
        raise Blocked('unsupported_link', 'invalid link encoding', document, line) from error
    if (not path or path.startswith('/') or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', path)
            or any(c in path for c in '\\:?#%') or any(ord(c) < 32 or ord(c) == 127 for c in path + fragment)):
        raise Blocked('unsafe_link', 'expected a repository-relative Markdown path; external references are not followed', document, line)
    parts = document.split('/')[:-1]
    for part in path.split('/'):
        if part == '..':
            if not parts:
                raise Blocked('unsafe_link', 'decoded path escapes the source checkout', document, line)
            parts.pop()
        elif part and part != '.':
            if part.casefold() == '.git':
                raise Blocked('unsafe_link', 'Git metadata is not a source document', document, line)
            parts.append(part)
    result = '/'.join(parts)
    if not result.lower().endswith('.md'):
        raise Blocked('unsupported_link', 'selected links must name Markdown documents', document, line)
    return Link(result, fragment)


def links(cell: str, document: str, line: int) -> list[Link]:
    result = []
    pos = 0
    while True:
        match = LINK.match(cell, pos)
        if not match:
            raise Blocked('unsupported_link', 'expected inline Markdown links separated by semicolons', document, line)
        result.append(local_link(match[1] or match[2], document, line))
        tail = cell[match.end():].lstrip()
        if not tail:
            return result
        if not tail.startswith(';'):
            raise Blocked('unsupported_link', 'unexpected text after selected link', document, line)
        pos = len(cell) - len(tail[1:].lstrip())


def cells(line: str) -> tuple[str, ...]:
    text = line.strip()
    if not (text.startswith('|') and text.endswith('|')):
        return ()
    return tuple(cell.strip() for cell in text[1:-1].split('|'))


def prd_label(label: str, prd: str) -> bool:
    return re.match(rf'^{prd}(?=$|[\s|:–—-])', label) is not None


def selected_row(doc: Document, prd: str) -> tuple[int, tuple[str, ...]]:
    starts = [i for i, title in doc.headings() if title == 'Available sources']
    if len(starts) != 1:
        raise Blocked('unsupported_map', 'expected one Available sources section', doc.path)
    start = starts[0]
    end = min((i for i, _ in doc.headings() if i > start), default=len(doc.lines) + 1)
    region = list(enumerate(doc.lines[start:end - 1], start + 1))
    headers = [line for line, text in region if cells(text) == MAP_HEADER]
    if len(headers) != 1:
        raise Blocked('unsupported_map', 'expected one supported PRD source table', doc.path, start)
    header = headers[0]
    if header >= len(doc.lines) or not table_divider(cells(doc.lines[header]), len(MAP_HEADER)):
        raise Blocked('unsupported_map', 'expected Markdown table separator', doc.path, header + 1)
    selected = [(i, cells(text)) for i, text in region if i > header
                and prd_label(text.lstrip().removeprefix('|').lstrip(), prd)]
    if not selected:
        raise Blocked('missing_selection', 'PRD is not listed in the supported source map', doc.path, start)
    if len(selected) != 1:
        raise Blocked('ambiguous_selection', 'multiple selected PRD rows; ask the source owner to resolve the map', doc.path, selected[0][0])
    line, row = selected[0]
    if len(row) != len(MAP_HEADER):
        raise Blocked('unsupported_map', 'selected row must have four pipe-delimited cells', doc.path, line)
    return line, row


def table_divider(row: tuple[str, ...], width: int) -> bool:
    return len(row) == width and all(re.fullmatch(r':?-{3,}:?', cell) for cell in row)


@dataclass(frozen=True)
class RegistryRow:
    category: str
    path: str
    status: str
    line: int


def registry_rows(doc: Document, prd: str, wanted: set[str]) -> list[RegistryRow]:
    headers = [i for i, line in enumerate(doc.lines, 1) if cells(line) == REGISTRY_HEADER]
    if len(headers) != 1:
        raise Blocked('unsupported_registry', 'expected one supported document registry table', doc.path)
    header = headers[0]
    if header >= len(doc.lines) or not table_divider(cells(doc.lines[header]), len(REGISTRY_HEADER)):
        raise Blocked('unsupported_registry', 'expected Markdown table separator', doc.path, header + 1)
    result = []
    for i, text in enumerate(doc.lines[header + 1:], header + 2):
        row = cells(text)
        if not row:
            continue
        category = row[0].lower()
        selected_prd = category in {'prd source', 'prd change source'} and len(row) > 1 and prd_label(row[1], prd)
        # Use selected paths as well as ID-labeled rows. Do not resolve unrelated files on disk.
        try:
            if len(row) != len(REGISTRY_HEADER):
                raise Blocked('unsupported_registry', 'expected six pipe-delimited registry cells', doc.path, i)
            target, = links(row[5], doc.path, i)
        except (Blocked, ValueError) as error:
            if selected_prd:
                raise Blocked('unsupported_registry', 'selected registry row must name one supported local link', doc.path, i) from error
            continue
        selected_revision = (target.path.startswith(f'{ARCH}/active/{prd}/')
                             and target.path.count('/') == ARCH.count('/') + 4
                             and target.path.rsplit('/', 1)[-1] in {'architecture.md', 'questions.md', *COMPANIONS})
        if selected_prd or selected_revision or target.path in wanted:
            if target.fragment or not row[2] or len(row[2]) > 240:
                raise Blocked('unsupported_registry', 'expected a document-level link and bounded declared status', doc.path, i)
            result.append(RegistryRow(category, target.path, row[2], i))
    return result


def architecture(snapshot: Snapshot, prd: str) -> list[tuple[str, Link]]:
    base = f'{ARCH}/active/{prd}'
    candidates = [path for path in snapshot.tree if path.startswith(base + '/') and path.count('/') == base.count('/') + 1]
    if len(candidates) != 1:
        code = 'missing_revision' if not candidates else 'ambiguous_revision'
        raise Blocked(code, 'expected exactly one active architecture revision for the selected PRD', base)
    revision = candidates[0]
    if snapshot.tree[revision][0] != '040000' or not re.fullmatch(r'r[1-9][0-9]*', revision.split('/')[-1]):
        raise Blocked('unsupported_revision', 'expected a physical r<number> active revision', revision)
    result = [('consolidated_architecture', Link(f'{ARCH}/consolidated/architecture.md', '')),
              ('consolidated_questions', Link(f'{ARCH}/consolidated/questions.md', '')),
              ('active_architecture', Link(f'{revision}/architecture.md', '')),
              ('active_questions', Link(f'{revision}/questions.md', ''))]
    result.extend((role, Link(f'{revision}/{name}', '')) for name, role in COMPANIONS.items()
                  if f'{revision}/{name}' in snapshot.tree)
    return result


def source_index(snapshot: Snapshot, prd: str) -> dict:
    if not PRD.fullmatch(prd):
        raise Blocked('invalid_prd', 'supply one explicit PRD identifier in PRD000 form')
    snapshot.inventory()
    source_map = snapshot.document(SOURCE_MAP)
    line, row = selected_row(source_map, prd)
    if row[1] == 'No local PRD supplied':
        raise Blocked('missing_source', 'source map declares no local PRD export', SOURCE_MAP, line)
    export, *changes = links(row[1], SOURCE_MAP, line)
    contexts = links(row[2], SOURCE_MAP, line)
    if not export.path.startswith(f'{HUB}/prds/active/{prd}/'):
        raise Blocked('role_conflict', 'first linked source must be a protected export for the selected PRD', export.path)
    if any(not change.path.startswith(f'{HUB}/prds/changelogs/') for change in changes):
        raise Blocked('role_conflict', 'additional organization sources must be linked change records', SOURCE_MAP, line)
    if any(not context.path.startswith('context/') for context in contexts):
        raise Blocked('role_conflict', 'working context must be linked from the repository context area', SOURCE_MAP, line)
    # Read the exact map target, not another filename from the tree (even if one looks newer).
    selected = [('protected_prd', export), *[('post_signoff_change', link) for link in changes],
                *[('working_context', link) for link in contexts]]
    if len({link.path for _, link in selected}) != len(selected):
        raise Blocked('ambiguous_selection', 'duplicate selected source targets in map row', SOURCE_MAP, line)
    for _, link in selected:
        snapshot.document(link.path)
    designs = architecture(snapshot, prd)
    registry = snapshot.document(REGISTRY)
    needed = {link.path for _, link in selected + designs} | {path for _, path in GUIDES} | {SOURCE_MAP}
    # A registered direct companion that is missing on disk must also block the selection.
    revision = designs[2][1].path.rsplit('/', 1)[0]
    companions = {f'{revision}/{name}' for name in COMPANIONS}
    rows = registry_rows(registry, prd, needed | companions)
    for category, paths in (('prd source', {export.path}), ('prd change source', {link.path for link in changes})):
        actual = [r.path for r in rows if r.category == category]
        if len(actual) != len(paths) or set(actual) != paths:
            raise Blocked('registry_conflict', f'selected map and registry disagree on {category} paths; ask the source owner',
                          REGISTRY, next((r.line for r in rows if r.category == category), None))
    for r in rows:
        if r.path.startswith(f'{ARCH}/active/{prd}/') and r.path not in needed:
            if r.path not in companions:
                raise Blocked('registry_conflict', 'registered active revision differs from the observed inventory', REGISTRY, r.line)
            raise Blocked('missing_source', 'registered active companion is absent at the observed commit', r.path)
    records = []
    for role, link in selected + designs + [(role, Link(path, '')) for role, path in GUIDES]:
        doc = snapshot.document(link.path)
        matches = [r for r in rows if r.path == link.path]
        if len(matches) > 1 or (not matches and (role, link) in designs):
            raise Blocked('registry_conflict', 'expected an unambiguous registry entry for selected document', link.path)
        statuses = doc.status()
        for r in matches:
            statuses.append({'text': r.status, 'path': REGISTRY, 'line': r.line, 'from': 'registry'})
        records.append(record(snapshot, role, doc, [doc.reference(link.fragment)], statuses))
    records.append(record(snapshot, 'source_map', source_map,
                          [{'section': 'Available sources', 'line': line}], source_map.status()))
    records.append(record(snapshot, 'document_registry', registry,
                          [{'line': r.line} for r in rows], registry.status()))
    snapshot.finish()
    return {'version': 1, 'state': 'source lookup observed', 'prd': prd, 'commit': snapshot.commit,
            'documents': records, 'shared_meeting_notes': 'not established; deferred',
            'authority': 'Declared source evidence only; not approval, deployment, task readiness or launch permission. Resolve material conflicts with the source owner.'}


def record(snapshot: Snapshot, role: str, doc: Document, references: list[dict], statuses: list[dict]) -> dict:
    return {'role': role, 'commit': snapshot.commit, 'path': doc.path, 'sha256': doc.sha256,
            'references': references, 'declared_status': statuses}
