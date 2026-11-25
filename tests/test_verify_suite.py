"""Real verifier subprocesses with import and execution markers in a disposable kit."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_factory_job import clean_env

ROOT = Path(__file__).resolve().parents[1]
FILE_TOOLS = ("DCC_PI_EXECUTABLE", "DCC_HERDR_EXECUTABLE", "DCC_PI_SDK_MODULE", "DCC_B3_NODE", "DCC_B3_OPENSPEC")
CANARY = "synthetic-env-canary-not-for-output"
MARKER = '''import json, os, sys, unittest
from pathlib import Path


def record(kind):
    with Path(os.environ['MARKER_TRACE']).open('a') as out:
        out.write(json.dumps([kind, __name__, __file__, sys.executable, os.environ.get('MARKER_CANARY')]) + '\\n')


record('import')


class Marker(unittest.TestCase):
    def test_once(self):
        record('run')
        if os.environ.get('MARKER_FAIL') == __name__:
            self.fail('fixture failed deliberately')
'''


class SuiteFixture:
    def __init__(self, root: Path, *, platform: str = 'darwin', kernel_problem: str | None = None):
        self.root = root
        self.tests = root / 'tests'
        self.cwd = root / 'unrelated cwd'
        self.home = root / 'empty home'
        self.bin = root / 'bin'
        self.tmp = root / 'tmp'
        self.agent = root / 'agent'
        self.sessions = root / 'sessions'
        self.xdg = root / 'xdg'
        lib = root / 'scripts/lib'
        for name in (self.tests, self.cwd, self.home, self.bin, self.tmp, self.agent, self.sessions, self.xdg, lib):
            name.mkdir(parents=True)
        self.cli = root / 'scripts/verify-suite.py'
        shutil.copyfile(ROOT / 'scripts/verify-suite.py', self.cli)
        profiles = (ROOT / 'scripts/lib/verification_profiles.py').read_text()
        # In the copy only, install a tiny inventory and model the host kernel.
        # The production CLI/selection/child/namespace code is unchanged.
        overrides = f'''
sys.platform = {platform!r}
PROFILE_SUITES = {{NATIVE: ('test_native_marker',), LINUX_SECURITY: ('test_linux_marker',)}}
PROFILE_RESOURCES = ()


def linux_kernel_checks():
    return [('/proc', None), ('inotify', None), ('Landlock', {kernel_problem!r})]


'''
        boundary = 'if __name__ == "__main__":'
        assert profiles.count(boundary) == 1
        (lib / 'verification_profiles.py').write_text(profiles.replace(boundary, overrides + boundary))
        self.add_test('test_native_marker')
        self.add_test('test_linux_marker')
        self.trace = root / 'marker.jsonl'
        self.namespace = root / 'namespace.txt'
        self.tools = {key: str(self.bin / key) for key in FILE_TOOLS}
        for key, value in self.tools.items():
            self.executable(Path(value), '#!/bin/sh\nexit 0\n', 0o644 if key in ('DCC_PI_SDK_MODULE', 'DCC_B3_OPENSPEC') else 0o755)
        for name in ('git', 'node'):
            self.executable(self.bin / name, '#!/bin/sh\nexit 0\n')

    def add_test(self, name):
        (self.tests / f'{name}.py').write_text(MARKER)

    def executable(self, path, content, mode=0o755):
        path.write_text(content)
        path.chmod(mode)

    def unshare(self, exit_code):
        self.executable(self.bin / 'unshare', '#!/bin/sh\nprintf "%s\\n" "$*" > "$NAMESPACE_MARKER"\n'
                        f'exit {exit_code}\n')

    def run(self, *args, complete=True, **overrides):
        env = clean_env(self.home) | {
            'PATH': str(self.bin), 'TMPDIR': str(self.tmp), 'PI_CODING_AGENT_DIR': str(self.agent),
            'PI_CODING_AGENT_SESSION_DIR': str(self.sessions), 'XDG_CONFIG_HOME': str(self.xdg),
            'MARKER_TRACE': str(self.trace), 'NAMESPACE_MARKER': str(self.namespace), 'MARKER_CANARY': CANARY,
        }
        if complete:
            env.update(self.tools)
        return subprocess.run([sys.executable, '-B', str(self.cli), *args], cwd=self.cwd, env=env | overrides,
                              capture_output=True, text=True, timeout=30, check=False)

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []


class VerifierBoundaryTest(unittest.TestCase):
    def fixture(self, **kwargs):
        temp = tempfile.TemporaryDirectory(prefix='dcc-verifier-fixture-')
        self.addCleanup(temp.cleanup)
        return SuiteFixture(Path(temp.name).resolve(), **kwargs)

    def stopped(self, fixture, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('no test was discovered, imported or started', result.stderr)
        self.assertEqual(fixture.records(), [])
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def selection(self, fixture, result, selected, excluded):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'SELECTED  {selected}', result.stdout)
        self.assertRegex(result.stdout, rf'NOT VERIFIED \([^)]* excluded\)  {excluded}')
        self.assertNotIn('full suite', result.stdout.lower())
        self.assertEqual(fixture.records(), [[phase, selected, str(fixture.tests / f'{selected}.py'), sys.executable, CANARY]
                                             for phase in ('import', 'run')])
        self.assertEqual(list(fixture.cwd.iterdir()), [])

    def test_native_runs_from_relocated_package_without_linux_tools(self):
        f = self.fixture()
        self.assertFalse((f.bin / 'unshare').exists())
        self.selection(f, f.run(), 'test_native_marker', 'test_linux_marker')
        self.assertFalse(f.namespace.exists())

    def test_invalid_profile_never_imports(self):
        f = self.fixture()
        result = f.run('--profile', 'all')
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid choice', result.stderr)
        self.assertIn('native', result.stderr)
        self.assertIn('linux-security', result.stderr)
        self.assertEqual(f.records(), [])

    def test_missing_and_invalid_prerequisites_aggregate_before_import(self):
        f = self.fixture()
        (f.bin / 'node').unlink()
        result = f.run(complete=False, DCC_PI_EXECUTABLE='relative', DCC_HERDR_EXECUTABLE=str(f.bin),
                       DCC_B3_NODE=f.tools['DCC_B3_OPENSPEC'])
        self.stopped(f, result)
        for variable in FILE_TOOLS + ('node',):
            self.assertEqual(result.stderr.count(f'FAIL  {variable}:'), 1, result.stderr)
        for reason in ('not an absolute path', 'not name an existing file', 'not executable', 'is not set'):
            self.assertIn(reason, result.stderr)
        self.assertIn('NOT VERIFIED (linux-security excluded)', result.stdout)

    def test_check_reports_coverage_but_does_not_import_or_run(self):
        f = self.fixture()
        result = f.run('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS  coverage', result.stdout)
        self.assertIn('selected tests NOT VERIFIED', result.stdout)
        self.assertEqual(f.records(), [])
        self.assertFalse(f.namespace.exists())

    def test_failing_child_status_passes_through(self):
        f = self.fixture()
        result = f.run(MARKER_FAIL='test_native_marker')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('fixture failed deliberately', result.stderr)
        self.assertEqual([r[0:2] for r in f.records()], [['import', 'test_native_marker'], ['run', 'test_native_marker']])

    def test_linux_profile_refuses_mac_before_test_import(self):
        f = self.fixture()
        f.unshare(0)
        result = f.run('--profile', 'linux-security')
        self.stopped(f, result)
        self.assertIn('linux-security requires Linux', result.stderr)
        self.assertIn('NOT VERIFIED (native excluded)', result.stdout)
        self.assertFalse(f.namespace.exists(), 'must not try Linux features on Darwin')

    def test_simulated_linux_missing_kernel_and_namespace_fail_together(self):
        f = self.fixture(platform='linux', kernel_problem='Linux ABI not available in fixture')
        f.unshare(19)
        result = f.run('--profile', 'linux-security', '--check', DCC_PI_EXECUTABLE='')
        self.stopped(f, result)
        self.assertIn('FAIL  Landlock: Linux ABI not available', result.stderr)
        self.assertIn('FAIL  unshare: user/network namespace probe failed with status 19', result.stderr)
        self.assertIn('FAIL  DCC_PI_EXECUTABLE:', result.stderr)
        self.assertEqual(f.namespace.read_text().strip(), '-Urn -- /bin/true')

    def test_simulated_linux_only_runs_selected_security_tests(self):
        f = self.fixture(platform='linux')
        f.unshare(0)
        check = f.run('--profile', 'linux-security', '--check', complete=False, DCC_PI_EXECUTABLE=f.tools['DCC_PI_EXECUTABLE'])
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual(f.records(), [])
        result = f.run('--profile', 'linux-security', complete=False, DCC_PI_EXECUTABLE=f.tools['DCC_PI_EXECUTABLE'])
        self.selection(f, result, 'test_linux_marker', 'test_native_marker')
        self.assertEqual(f.namespace.read_text().strip(), '-Urn -- /bin/true')

    def test_unclassified_new_test_fails_without_import(self):
        f = self.fixture()
        f.add_test('test_unclassified')
        result = f.run()
        self.stopped(f, result)
        self.assertIn('unclassified test: test_unclassified.Marker.test_once', result.stderr)

    def test_missing_declared_test_module_fails_without_import(self):
        f = self.fixture()
        (f.tests / 'test_native_marker.py').unlink()
        result = f.run('--check')
        self.stopped(f, result)
        self.assertIn('native selector has no tests: test_native_marker', result.stderr)


if __name__ == '__main__':
    unittest.main()
