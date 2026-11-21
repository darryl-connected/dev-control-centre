"""Synthetic local hub contracts, real Git and audited CLI/filesystem boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_factory_job import clean_env
from test_setup import APPROVE, KIT, SetupFixture, evidence, file_map, write

EXPORT = 'knowledge-hub/prds/active/PRD123/Product (sample) export.md'
OTHER = 'knowledge-hub/prds/active/PRD124/Unrelated.md'
NEWER = 'knowledge-hub/prds/active/PRD123/9999-looks-newer.md'
CHANGE = 'knowledge-hub/prds/changelogs/CL-7 (sample).md'
CONTEXT = 'context/PRD900-Historical synthesis.md'
EXTRA_CONTEXT = 'context/shared-demo.md'
MAP = 'knowledge-hub/prds/source-map.md'
REGISTRY = 'knowledge-hub/index.md'
ACTIVE = 'knowledge-hub/architecture/active/PRD123/r1'
UNRELATED_ACTIVE = 'knowledge-hub/architecture/active/PRD124/r3'
CONS = 'knowledge-hub/architecture/consolidated'
MAPPING = '.dcc/knowledge.json'
MAP_LINK = '[Export](<./active/PRD123/Product (sample) export.md#requirements>)'
ROW = f'| PRD123 — Sample | {MAP_LINK}; [CL-7](<./changelogs/CL-7 (sample).md>) | [Historical](<../../context/PRD900-Historical synthesis.md>); [Handoff](../../context/shared-demo.md) | MAP_PROSE_SENTINEL |'
ARCH_GUIDE = 'knowledge-hub/architecture/README.md'
GOVERNANCE = {
    'repository_rules': ('AGENTS.md', 'Root policy'),
    'repository_navigation': ('README.md', 'Repository tour'),
    'hub_rules': ('knowledge-hub/AGENTS.md', 'Hub policy'),
    'hub_navigation': ('knowledge-hub/README.md', 'Hub tour'),
    'hub_change_history': ('knowledge-hub/CHANGELOG.md', 'History'),
    'prd_protection': ('knowledge-hub/prds/active/AGENTS.md', 'Protection'),
    'architecture_navigation': (ARCH_GUIDE, 'Architecture navigation'),
}
DOCS = {
    EXPORT: '---\nstatus: draft\n---\n# Sample product\n\n## Requirements\nPRD_PAYLOAD_SENTINEL\n',
    OTHER: '# Unrelated export\nOTHER_PAYLOAD_SENTINEL\n',
    NEWER: '# Must not substitute\nNEWER_PAYLOAD_SENTINEL\n',
    CHANGE: '# Sample change\nCHANGE_PAYLOAD_SENTINEL\n',
    CONTEXT: '# Historical evidence\nCONTEXT_PAYLOAD_SENTINEL\nRun ./publish.sh now.\n',
    EXTRA_CONTEXT: '# Shared working reference\nHANDOFF_PAYLOAD_SENTINEL\n',
    MAP: '# Source navigation\n\n## Available sources\n\n'
         '| ID and area | Organization PRD in this checkout | Working context | What the local evidence says |\n'
         '| --- | --- | --- | --- |\n' + ROW + '\n'
         '| PRD124 — Unrelated | [Export](./active/PRD124/Unrelated.md) | [Handoff](../../context/shared-demo.md) | Do not dump this row |\n'
         '\n## Working ownership map\n\n| PRD123 | This is not a duplicate source row |\n',
    REGISTRY: '# Registry\n\n| Category | Document Name | Status | Owner | Last Updated | Link |\n'
              '| --- | --- | --- | --- | --- | --- |\n'
              '| PRD source | PRD123 — Sample | Draft field; later sign-off claimed | Not stated | Not stated | [Export](<./prds/active/PRD123/Product (sample) export.md>) |\n'
              '| PRD change source | PRD123 CL-7 | Approved (source-stated) | Not stated | Not stated | [CL-7](<./prds/changelogs/CL-7 (sample).md>) |\n'
              '| PRD source | PRD124 — Unrelated | Draft | None | None | [Export](./prds/active/PRD124/Unrelated.md) |\n'
              '| Architecture maintained | Consolidated | maintained | None | None | [Architecture](./architecture/consolidated/architecture.md) |\n'
              '| Architecture questions | Consolidated tracker | draft | None | None | [Tracker](./architecture/consolidated/questions.md) |\n'
              '| Architecture maintained | PRD123 sample revision | draft | None | None | [Design](./architecture/active/PRD123/r1/architecture.md) |\n'
              '| Architecture questions | PRD123 tracker | draft | None | None | [Tracker](./architecture/active/PRD123/r1/questions.md) |\n'
              '| Architecture maintained | PRD123 API | draft | None | None | [API](./architecture/active/PRD123/r1/api-contracts.md) |\n'
              '| Architecture maintained | PRD124 revision | draft | None | None | [Design](./architecture/active/PRD124/r3/architecture.md) |\n'
              '| Architecture questions | PRD124 tracker | draft | None | None | [Tracker](./architecture/active/PRD124/r3/questions.md) |\n',
    f'{ACTIVE}/architecture.md': '# Active technical design\nACTIVE_DESIGN_SENTINEL\n',
    f'{ACTIVE}/questions.md': '# Active decisions to resolve\nACTIVE_QUESTIONS_SENTINEL\n',
    f'{ACTIVE}/api-contracts.md': '# Candidate API details\nAPI_SENTINEL\n',
    f'{UNRELATED_ACTIVE}/architecture.md': '# Other design\n',
    f'{UNRELATED_ACTIVE}/questions.md': '# Other questions\n',
    f'{CONS}/architecture.md': '# Shared technical design\nSHARED_DESIGN_SENTINEL\n',
    f'{CONS}/questions.md': '# Shared decisions to resolve\nSHARED_QUESTIONS_SENTINEL\n',
    'publish.sh': 'exit 47\n',
    **{path: f'# {heading}\nGOVERNANCE_PAYLOAD_SENTINEL\n' for path, heading in GOVERNANCE.values()},
}
EXPECTED = {
    'protected_prd': (EXPORT, 6, 'Requirements'),
    'post_signoff_change': (CHANGE, 1, 'Sample change'),
    'working_context': (CONTEXT, 1, 'Historical evidence'),
    'consolidated_architecture': (f'{CONS}/architecture.md', 1, 'Shared technical design'),
    'consolidated_questions': (f'{CONS}/questions.md', 1, 'Shared decisions to resolve'),
    'active_architecture': (f'{ACTIVE}/architecture.md', 1, 'Active technical design'),
    'active_questions': (f'{ACTIVE}/questions.md', 1, 'Active decisions to resolve'),
    'active_api_contracts': (f'{ACTIVE}/api-contracts.md', 1, 'Candidate API details'),
    'source_map': (MAP, 7, 'Available sources'),
    **{role: (path, 1, title) for role, (path, title) in GOVERNANCE.items()},
}

# Optional per-process origin trace for relocated CLI tests. Code reads (including imports)
# and code objects executed by Python are observed, not inferred from sys.path or shipped bytes.
ORIGIN_AUDIT = r'''
import atexit, json, os, sys

def watch_origins(trace, script, args):
    if not trace:
        return
    reads = set()
    executed = set()

    def origin(event, values):
        if event == 'open' and not isinstance(values[0], int):
            path = os.fsdecode(values[0])
            # Importlib probes cache paths even with -B; a missing cache supplies no code.
            if path.endswith(('.py', '.pyc', '.so', '.pyd')) and os.path.isfile(path):
                reads.add(os.path.realpath(path))
        elif event == 'exec':
            path = values[0].co_filename
            if not path.startswith('<'):
                executed.add(os.path.realpath(path))

    def save_origins():
        with open(trace, 'a', encoding='utf-8') as handle:
            print(json.dumps({'script': script, 'args': args, 'code_reads': sorted(reads),
                              'executed': sorted(executed)}), file=handle)

    sys.addaudithook(origin)
    atexit.register(save_origins)
'''


# Record at the real Popen and file-open boundaries. Git itself is real; it is separately
# constrained by the checked argv/env, and outside-source reads by Python are trapped.
AUDIT = ORIGIN_AUDIT + r'''
import runpy
trace, origin_trace, script, outside, action, drift_file, drift_value, *args = sys.argv[1:]
watch_origins(origin_trace, script, args)
seen_target = False
changed = False

def record(event, values):
    global seen_target, changed
    if event == 'open' and not isinstance(values[0], int):
        target = os.fsdecode(values[0])
        forbidden = os.path.realpath(target) == outside or target.endswith(('/auth.json', '/publish.sh'))
        if forbidden:
            with open(trace, 'a', encoding='utf-8') as handle:
                print(json.dumps({'forbidden': 'open', 'path': target}), file=handle)
            raise RuntimeError('forbidden file read')
        if action == 'bytes' and target == drift_file:
            seen_target = True
    if event == 'subprocess.Popen':
        with open(trace, 'a', encoding='utf-8') as handle:
            print(json.dumps({'exe': values[0], 'argv': values[1], 'cwd': values[2], 'env': values[3]}), file=handle)
        if not changed and ((action == 'bytes' and seen_target) or (action == 'head' and 'ls-tree' in values[1])):
            changed = True
            with open(drift_file, 'w', encoding='utf-8') as handle:
                handle.write(drift_value)
            with open(trace, 'a', encoding='utf-8') as handle:
                print(json.dumps({'injected': action}), file=handle)
    if event in {'os.system', 'os.exec', 'os.posix_spawn', 'socket.connect'}:
        with open(trace, 'a', encoding='utf-8') as handle:
            print(json.dumps({'forbidden': event}), file=handle)
        raise RuntimeError('forbidden fixture boundary')

sys.addaudithook(record)
sys.path.insert(0, os.path.dirname(script))
sys.argv = [script, *args]
runpy.run_path(script, run_name='__main__')
'''


class HubFixture:
    def __init__(self, root: Path, kit: Path = KIT, *, origin_trace: Path | None = None):
        self.fx = SetupFixture(root, kit)
        self.fx.user_settings()
        self.root, self.kit, self.workspace = root, kit, self.fx.workspace
        self.origin_trace = origin_trace
        self.source = root / 'synthetic hub checkout'
        self.source.mkdir()
        self.trace = root / 'knowledge-audit.jsonl'
        self.plan = root / 'knowledge-plan.json'
        self.outside = root / 'outside-source-sentinel.md'
        write(self.outside, 'OUTSIDE_SENTINEL_BYTES')
        git_path = shutil.which('git')
        assert git_path is not None
        self.git_path = git_path
        self.git('init', '-q')
        for path, content in DOCS.items():
            write(self.source / path, content, 0o644)
        self.commit = self.save('synthetic sources')
        plan = self.fx.inspect()
        assert plan.returncode == 0, plan.stderr
        write(self.fx.plan, plan.stdout)
        applied = self.fx.apply(*APPROVE)
        assert applied.returncode == 0, applied.stderr
        self.results: list[dict] = []
        self.maps: dict = {}

    def git(self, *args: str) -> str:
        return subprocess.run([self.git_path, '-C', str(self.source), *args], env=clean_env(self.fx.home),
                              text=True, capture_output=True, check=True, timeout=10).stdout.strip()

    def save(self, name: str) -> str:
        self.git('add', '-A')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', name)
        return self.git('rev-parse', 'HEAD')

    def run(self, *arguments: str, drift: tuple[str, str, str] = ('', '', ''),
            env: dict | None = None) -> subprocess.CompletedProcess[str]:
        python = [sys.executable, '-B', '-S'] if self.origin_trace is not None else [sys.executable, '-B']
        result = subprocess.run([*python, '-c', AUDIT, str(self.trace), str(self.origin_trace or ''),
                                 str(self.kit / 'scripts/knowledge.py'), str(self.outside), *drift, *arguments],
                                cwd=self.root, text=True, capture_output=True,
                                env=clean_env(self.fx.home) | {
                                    'GIT_DIR': '/ambient-override-must-not-be-used', 'GIT_CONFIG_COUNT': '1',
                                    'GIT_CONFIG_KEY_0': 'filter.fixture.clean', 'GIT_CONFIG_VALUE_0': 'false',
                                    'UNKNOWN_PROVIDER_TOKEN': 'synthetic-credential-not-for-child',
                                } | (env or {}), check=False, timeout=25)
        self.results.append({'args': arguments, 'exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        return result

    def inspect(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run('inspect', '--workspace', str(self.workspace), *extra)

    def apply(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run('apply', '--plan', str(self.plan), *extra)

    def lookup(self, prd: str = 'PRD123', **kwargs) -> subprocess.CompletedProcess[str]:
        return self.run('sources', '--workspace', str(self.workspace), '--prd', prd, **kwargs)

    def configure(self) -> None:
        plan = self.inspect('--checkout', str(self.source))
        assert plan.returncode == 0, plan.stderr
        write(self.plan, plan.stdout)
        applied = self.apply('--approve')
        assert applied.returncode == 0, applied.stderr

    def snapshot(self) -> dict:
        return self.fx.snapshot() | {'source': file_map(self.source), 'source_index_hex': (self.source / '.git/index').read_bytes().hex(),
                                     'outside_source': self.outside.read_bytes().hex()}

    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []


def assert_git_boundary(test: unittest.TestCase, hub: HubFixture) -> None:
    for event in hub.records():
        test.assertNotIn('forbidden', event)
        if 'injected' in event:
            continue
        argv = event['argv']
        test.assertEqual(event['exe'], hub.git_path)
        test.assertEqual(argv[:3], [hub.git_path, '--no-optional-locks', '-C'])
        if argv[3] == hub.source.anchor:
            test.assertEqual(argv[4:-1], ['config', '--file', str(hub.source / '.git/config'), '--no-includes',
                                          '--name-only', '--get-regexp'])
            test.assertIn(r'filter\..*\.(process|clean)', argv[-1])
            command = argv[4:]
        else:
            test.assertEqual(argv[3:12], [str(hub.source), '-c', 'core.fsmonitor=false', '-c', f'core.attributesFile={os.devnull}',
                                         '-c', f'core.excludesFile={os.devnull}', '-c', f'core.hooksPath={os.devnull}'])
            command = argv[12:]
            test.assertNotEqual(command[0], 'config')
        permitted = (
            ['rev-parse', '--show-toplevel'], ['rev-parse', '--verify', 'HEAD^{commit}'], ['ls-files', '-v', '-z'],
            ['status', '--porcelain=v1', '-z', '--untracked-files=all', '--no-renames', '--ignore-submodules=all'],
        )
        if command and command[0] == 'cat-file':
            test.assertEqual(len(command), 3)
            test.assertIn(command[1], ('-s', 'blob'))
            test.assertRegex(command[2], r'^(?:[a-f0-9]{40}|[a-f0-9]{64})$')
        elif command and command[0] == 'config':
            pass  # The file-only config command is checked before dispatch above.
        elif command and command[0] == 'ls-tree':
            test.assertEqual(command[:-1], ['ls-tree', '-r', '-t', '-z', '--full-tree'])
            test.assertRegex(command[-1], r'^(?:[a-f0-9]{40}|[a-f0-9]{64})$')
        elif command and command[0] == 'diff-index':
            test.assertEqual(command[:-2], ['diff-index', '--cached', '--quiet', '--no-ext-diff', '--no-textconv', '--ignore-submodules=none'])
            test.assertEqual(command[-1], '--')
            test.assertRegex(command[-2], r'^(?:[a-f0-9]{40}|[a-f0-9]{64})$')
        else:
            test.assertIn(command, permitted)
        required = {'LC_ALL': 'C', 'PI_OFFLINE': '1', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_LAZY_FETCH': '1',
                    'GIT_ALLOW_PROTOCOL': '', 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_ATTR_NOSYSTEM': '1', 'GIT_NO_REPLACE_OBJECTS': '1'}
        test.assertEqual(set(event['env']) - {'PATH', 'TMPDIR', 'SYSTEMROOT'}, set(required))
        for name, value in required.items():
            test.assertEqual(event['env'][name], value)
        test.assertIsNone(event['cwd'])


def assert_index(test: unittest.TestCase, result: subprocess.CompletedProcess[str], commit: str) -> dict:
    test.assertEqual(result.returncode, 0, result.stderr)
    payload = json.loads(result.stdout)
    test.assertEqual(payload['state'], 'source lookup observed')
    test.assertEqual(payload['prd'], 'PRD123')
    test.assertEqual(payload['commit'], commit)
    test.assertEqual(payload['shared_meeting_notes'], 'not established; deferred')
    test.assertEqual(payload['authority'], 'Declared source evidence only; not approval, deployment, task readiness or launch permission. Resolve material conflicts with the source owner.')
    records = payload['documents']
    test.assertCountEqual([(item['role'], item['path']) for item in records],
                          [(role, path) for role, (path, _, _) in EXPECTED.items()]
                          + [('document_registry', REGISTRY), ('working_context', EXTRA_CONTEXT)])
    for item in records:
        role, path = item['role'], item['path']
        test.assertEqual(set(item), {'role', 'path', 'sha256', 'commit', 'references', 'declared_status'})
        test.assertEqual(item['commit'], commit)
        test.assertEqual(item['sha256'], hashlib.sha256(DOCS[path].encode()).hexdigest())
        if role == 'document_registry':
            test.assertEqual(item['references'], [{'line': i} for i in (5, 6, 8, 9, 10, 11, 12)])
        else:
            line, title = (1, 'Shared working reference') if path == EXTRA_CONTEXT else EXPECTED[role][1:]
            expected = {'line': line, 'section': title}
            if role == 'protected_prd':
                expected['fragment'] = 'requirements'
            test.assertEqual(item['references'], [expected], path)
    by_role = {r['role']: r for r in records}
    test.assertEqual(by_role['protected_prd']['declared_status'], [
        {'text': 'draft', 'path': EXPORT, 'line': 2, 'from': 'frontmatter'},
        {'text': 'Draft field; later sign-off claimed', 'path': REGISTRY, 'line': 5, 'from': 'registry'},
    ])
    test.assertEqual(by_role['post_signoff_change']['declared_status'], [
        {'text': 'Approved (source-stated)', 'path': REGISTRY, 'line': 6, 'from': 'registry'},
    ])
    test.assertEqual(by_role['consolidated_architecture']['declared_status'], [
        {'text': 'maintained', 'path': REGISTRY, 'line': 8, 'from': 'registry'},
    ])
    for marker in ('SENTINEL', OTHER, NEWER, './publish.sh', 'This is not a duplicate source row'):
        test.assertNotIn(marker, result.stdout)
    return payload


class KnowledgeTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix='dcc-knowledge-', dir=os.environ.get('DCC_EVIDENCE'))
        self.addCleanup(temp.cleanup)
        self.hub = HubFixture(Path(temp.name).resolve())
        self.addCleanup(self.check_evidence)

    def check_evidence(self) -> None:
        evidence(self._testMethodName, {'cli': self.hub.results, 'audit': self.hub.records(), 'maps': self.hub.maps})
        assert_git_boundary(self, self.hub)

    def good(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_technical_diagnostic(self, text: str, surface: str) -> None:
        # Diagnostic vocabulary only, not an arbitrary-language detector. Omit echoed
        # fixture directory prefixes; technical knowledge, PRD and mapping terms are allowed.
        prose = text.replace(str(self.hub.root), '<fixture>').replace(str(self.hub.kit), '<kit>').lower()
        prose = prose.replace('checkout identity', 'checkout')  # Filesystem identity is technical.
        self.assertNotRegex(prose, r'\b(?:business|identity|voice|revenue|seven[- ]question|meetings?|fathom|location url|checkout url)\b',
                            f'knowledge CLI {surface} must not request excluded or deferred intake')

    def blocked(self, result: subprocess.CompletedProcess[str], code: str, path: str | None = None) -> dict:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')
        diagnostic = json.loads(result.stderr)['error']
        self.assertEqual(diagnostic['code'], code, diagnostic)
        self.assertIsInstance(diagnostic['detail'], str)
        self.assert_technical_diagnostic(diagnostic['detail'], code)
        if path is not None:
            self.assertEqual(diagnostic['path'], path)
        self.assertNotIn('OUTSIDE_SENTINEL_BYTES', result.stderr)
        self.assertNotIn(NEWER, result.stderr)
        return diagnostic

    def plan(self) -> dict:
        result = self.hub.inspect('--checkout', str(self.hub.source))
        plan = self.good(result)['plan']
        write(self.hub.plan, result.stdout)
        return plan

    def test_mapping_requires_approval_and_changes_exactly_one_workspace_file(self) -> None:
        h = self.hub
        h.maps['before'] = before = h.snapshot()
        plan = self.plan()
        self.assertEqual((plan['path'], plan['action'], plan['checkout'], plan['source_commit']), (MAPPING, 'create', str(h.source), h.commit))
        self.assertEqual(h.snapshot(), before)
        self.blocked(h.apply(), 'approval_required')
        self.assertEqual(h.snapshot(), before)
        applied = self.good(h.apply('--approve'))
        self.assertEqual(applied, {'ok': True, 'applied': {'path': MAPPING, 'action': 'create'}})
        path = h.workspace / MAPPING
        expected = json.dumps({'checkout': str(h.source), 'version': 1}, indent=2).encode() + b'\n'
        self.assertEqual(path.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        h.maps['after'] = after = h.snapshot()
        self.assertEqual(set(after['workspace']) - set(before['workspace']), {MAPPING})
        self.assertEqual(after | {'workspace': {k: v for k, v in after['workspace'].items() if k != MAPPING}}, before)
        self.blocked(h.apply('--approve'), 'stale_plan')
        rerun = h.inspect()
        self.assertEqual(self.good(rerun)['plan']['action'], 'unchanged')
        write(h.plan, rerun.stdout)
        self.assertEqual(self.good(h.apply('--approve'))['applied']['action'], 'unchanged')
        assert_index(self, h.lookup(), h.commit)
        self.assertEqual(h.snapshot(), after)

    def test_conflicting_malformed_and_symlink_mapping_refuse_without_writes(self) -> None:
        h = self.hub
        mapping = h.workspace / MAPPING
        self.plan()
        for body, code in (('{"version":1,"checkout":"/elsewhere"}\n', 'mapping_conflict'),
                           ('{"version":1,"version":1,"checkout":"/elsewhere"}\n', 'invalid_mapping'),
                           ('not JSON', 'invalid_mapping')):
            with self.subTest(code=code, body=body):
                write(mapping, body)
                before = h.snapshot()
                self.blocked(h.inspect('--checkout', str(h.source)), code, str(mapping))
                self.blocked(h.apply('--approve'), 'stale_plan')
                self.assertEqual(h.snapshot(), before)
        mapping.unlink()
        mapping.symlink_to(h.outside)
        before = h.snapshot()
        self.blocked(h.inspect('--checkout', str(h.source)), 'unsafe_path', str(mapping))
        self.blocked(h.apply('--approve'), 'stale_plan')
        self.assertEqual(h.snapshot(), before)

    def test_stale_plan_refuses_changed_prior_setup_or_new_commit(self) -> None:
        h = self.hub
        self.plan()
        append = h.workspace / '.pi/APPEND_SYSTEM.md'
        append.write_bytes(append.read_bytes() + b'\nlocal addition\n')
        before = h.snapshot()
        self.blocked(h.apply('--approve'), 'stale_plan')
        self.assertEqual(h.snapshot(), before)
        self.plan()
        (h.source / 'README.md').write_text('# New repository tour\n')
        h.save('manual local source update')
        before = h.snapshot()
        self.blocked(h.apply('--approve'), 'stale_plan')
        self.assertEqual(h.snapshot(), before)
        self.assertFalse((h.workspace / MAPPING).exists())

    def test_selected_role_commit_hash_references_and_source_claims(self) -> None:
        h = self.hub
        h.configure()
        h.maps['before'] = before = h.snapshot()
        result = h.lookup()
        assert_index(self, result, h.commit)
        h.maps['after'] = h.snapshot()
        self.assertEqual(h.maps['after'], before)
        h.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'manual new HEAD')
        new_head = h.git('rev-parse', 'HEAD')
        self.assertNotEqual(new_head, h.commit)
        assert_index(self, h.lookup(), new_head)

    def test_stale_selected_link_never_substitutes_newer_but_other_prd_works(self) -> None:
        h = self.hub
        h.configure()
        (h.source / EXPORT).unlink()
        commit = h.save('keep stale map and registry links')
        before = h.snapshot()
        error = self.blocked(h.lookup(), 'missing_source', EXPORT)
        self.assertEqual(error['prd'], 'PRD123')
        good = self.good(h.lookup('PRD124'))
        self.assertEqual(good['commit'], commit)
        self.assertEqual([r['path'] for r in good['documents'] if r['role'] == 'protected_prd'], [OTHER])
        self.assertNotIn(EXPORT, json.dumps(good))
        self.assertEqual(h.snapshot(), before)

    def test_ambiguous_map_revision_and_registry_disagreement(self) -> None:
        h = self.hub
        h.configure()
        for relative, body, code, path in (
            (MAP, DOCS[MAP].replace(ROW, ROW + '\n' + ROW), 'ambiguous_selection', MAP),
            ('knowledge-hub/architecture/active/PRD123/r9/architecture.md', '# Competing revision', 'ambiguous_revision', 'knowledge-hub/architecture/active/PRD123'),
            (REGISTRY, DOCS[REGISTRY].replace('Product (sample) export.md>)', '9999-looks-newer.md>)'), 'registry_conflict', REGISTRY),
            (REGISTRY, DOCS[REGISTRY] + DOCS[REGISTRY].splitlines()[4] + '\n', 'registry_conflict', REGISTRY),
            (REGISTRY, DOCS[REGISTRY].replace('/PRD123/r1/api-contracts.md', '/PRD123/r8/api-contracts.md'), 'registry_conflict', REGISTRY),
        ):
            with self.subTest(code=code, path=relative):
                write(h.source / relative, body)
                h.save(f'inject {code}')
                self.blocked(h.lookup(), code, path)
                if relative in DOCS:
                    write(h.source / relative, DOCS[relative])
                else:
                    (h.source / relative).unlink()
                h.save('restore navigation control')
                assert_index(self, h.lookup(), h.git('rev-parse', 'HEAD'))

    def test_missing_revision_and_registered_companion_block(self) -> None:
        h = self.hub
        h.configure()
        companion = f'{ACTIVE}/api-contracts.md'
        (h.source / companion).unlink()
        h.save('stale companion registry')
        self.blocked(h.lookup(), 'missing_source', companion)
        for name in ('architecture.md', 'questions.md'):
            (h.source / ACTIVE / name).unlink()
        h.save('no active design')
        self.blocked(h.lookup(), 'missing_revision', 'knowledge-hub/architecture/active/PRD123')

    def test_unsupported_selected_links_and_path_escapes_block(self) -> None:
        h = self.hub
        h.configure()
        for link, code in (
            ('[[export]]', 'unsupported_link'),
            ('[Export](<./active/PRD123/Product (sample) export.md> "title")', 'unsupported_link'),
            ('[Export](<./active/PRD123/Product (sample) export.md#not-present>)', 'unsupported_fragment'),
            (f'[Export](<{h.outside}>)', 'unsafe_link'),
            (f'[Export](<file://{h.outside}>)', 'unsafe_link'),
            ('[Export](https://example.invalid/source.md)', 'unsafe_link'),
            ('[Export](%2e%2e/%2e%2e/%2e%2e/outside-source-sentinel.md)', 'unsafe_link'),
            ('[Export](%2foutside-source-sentinel.md)', 'unsafe_link'),
            ('[Export](../../.git/config.md)', 'unsafe_link'),
        ):
            with self.subTest(link=link):
                write(h.source / MAP, DOCS[MAP].replace(MAP_LINK, link))
                h.save('unsupported input')
                before = h.snapshot()
                self.blocked(h.lookup(), code, EXPORT if code == 'unsupported_fragment' else MAP)
                self.assertEqual(h.snapshot(), before)
                self.assertEqual(self.good(h.lookup('PRD124'))['prd'], 'PRD124')
        write(h.source / MAP, DOCS[MAP].replace('Product (sample) export.md#', 'Product%20%28sample%29%20export.md#'))
        h.save('supported encoded path')
        self.assertEqual(self.good(h.lookup())['documents'][0]['path'], EXPORT)

    def test_committed_symlink_file_ancestor_and_gitlink_are_not_followed(self) -> None:
        h = self.hub
        h.configure()
        path = h.source / EXPORT
        path.unlink()
        path.symlink_to(h.outside)
        h.save('symlink leaf')
        before = h.snapshot()
        self.blocked(h.lookup(), 'unsafe_path', EXPORT)
        self.assertEqual(h.snapshot(), before)
        path.unlink()
        (h.source / NEWER).unlink()
        path.parent.rmdir()
        path.parent.symlink_to(h.outside.parent, target_is_directory=True)
        h.save('symlink ancestor')
        before = h.snapshot()
        self.blocked(h.lookup(), 'unsafe_path', EXPORT)
        self.assertEqual(h.snapshot(), before)
        path.parent.unlink()
        h.git('add', '-A')
        h.git('update-index', '--add', '--cacheinfo', f'160000,{h.commit},{path.parent.relative_to(h.source)}')
        h.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'gitlink ancestor')
        before = h.snapshot()
        self.blocked(h.lookup(), 'unsafe_path', EXPORT)
        self.assertEqual(h.snapshot(), before)

    def test_dirty_unsafe_config_missing_source_and_git_refused(self) -> None:
        h = self.hub
        h.configure()
        for kind in ('untracked', 'unstaged', 'staged', 'assume-unchanged', 'skip-worktree'):
            with self.subTest(dirty=kind):
                if kind == 'untracked':
                    write(h.source / 'untracked.md', 'new')
                elif kind in ('unstaged', 'staged'):
                    write(h.source / EXPORT, '# Dirty')
                    if kind == 'staged':
                        h.git('add', EXPORT)
                else:
                    h.git('update-index', '--' + kind, EXPORT)
                before = h.snapshot()
                self.blocked(h.lookup(), 'dirty_checkout', str(h.source))
                self.assertEqual(h.snapshot(), before)
                if kind == 'untracked':
                    (h.source / 'untracked.md').unlink()
                elif kind in ('unstaged', 'staged'):
                    h.git('restore', '--source=HEAD', '--staged', '--worktree', EXPORT)
                else:
                    h.git('update-index', '--no-' + kind, EXPORT)
        for key, val in (('filter.fixture.clean', f'touch "{h.root / "filter-ran"}"'),
                         ('filter.fixture.process', 'false'), ('include.path', str(h.outside))):
            with self.subTest(config=key):
                h.git('config', '--local', key, val)
                before = h.snapshot()
                self.blocked(h.lookup(), 'unsafe_git_config', str(h.source))
                self.assertEqual(h.snapshot(), before)
                self.assertFalse((h.root / 'filter-ran').exists())
                if key == 'include.path':
                    subprocess.run([h.git_path, 'config', '--file', str(h.source / '.git/config'), '--unset', key],
                                   cwd=h.root, env=clean_env(h.fx.home), check=True, timeout=10)
                else:
                    h.git('config', '--local', '--unset', key)
        assert_index(self, h.lookup(), h.commit)
        self.blocked(h.lookup(env={'PATH': str(h.root / 'missing-bin')}), 'git_unavailable', str(h.source))
        h.source.rename(h.root / 'parked source')
        self.blocked(h.lookup(), 'checkout_unavailable', str(h.source))

    def test_selected_bytes_and_head_drift_at_actual_subprocess_boundary(self) -> None:
        h = self.hub
        h.configure()
        self.blocked(h.lookup(drift=('bytes', str(h.source / EXPORT), '# Drifted after read\n')), 'snapshot_drift', EXPORT)
        self.assertEqual((h.source / EXPORT).read_text(), '# Drifted after read\n')
        h.git('restore', EXPORT)
        assert_index(self, h.lookup(), h.commit)
        h.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'alternate HEAD')
        other = h.git('rev-parse', 'HEAD')
        h.git('checkout', '--detach', h.commit)
        self.blocked(h.lookup(drift=('head', str(h.source / '.git/HEAD'), other + '\n')), 'snapshot_drift', str(h.source))
        self.assertEqual(h.git('rev-parse', 'HEAD'), other)
        assert_index(self, h.lookup(), other)

    def test_technical_cli_surfaces_and_workspace_boundaries(self) -> None:
        h = self.hub
        before = h.snapshot()
        error = self.blocked(h.inspect(), 'missing_checkout')
        self.assertEqual(error['detail'], 'supply the local source checkout path with --checkout')
        unmapped = self.blocked(h.lookup(), 'not_configured', str(h.workspace / MAPPING))
        self.assertIn('use explicit mapping inspect and apply', unmapped['detail'])
        invalid = self.blocked(h.lookup('any-latest'), 'invalid_prd')
        self.assertIn('one explicit PRD identifier in PRD000 form', invalid['detail'])
        self.blocked(h.inspect('--checkout', str(h.fx.repo)), 'checkout_overlap', str(h.fx.repo))
        self.blocked(h.inspect('--checkout', str(h.workspace)), 'checkout_overlap', str(h.workspace))
        self.blocked(h.inspect('--checkout', str(h.kit)), 'checkout_overlap', str(h.kit))
        missing = h.root / 'not a workspace'
        self.blocked(h.run('inspect', '--workspace', str(missing), '--checkout', str(h.source)), 'local_precondition')
        symlink = h.root / 'checkout symlink'
        symlink.symlink_to(h.source, target_is_directory=True)
        self.blocked(h.inspect('--checkout', str(symlink)), 'unsafe_path', str(symlink))
        for args in (('--help',), ('inspect', '--help'), ('apply', '--help'), ('sources', '--help'),
                     ('inspect',), ('apply', '--approve'), ('sources', '--workspace', str(h.workspace))):
            with self.subTest(args=args):
                output = h.run(*args)
                self.assertEqual(output.returncode, 0 if '--help' in args else 2, output.stderr)
                self.assert_technical_diagnostic(output.stdout + output.stderr, repr(args))
        self.assertEqual(h.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
