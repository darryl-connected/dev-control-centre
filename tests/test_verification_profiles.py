"""Independent shipped profile inventory and relocated verifier checks."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import test_e2e_factory as distribution
from test_factory_job import clean_env

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'scripts'))
from lib import verification_profiles as profiles

# Whole Linux class identities; each original method must stay in this suite.
LINUX_CLASSES = {'test_e2e_factory.RelocatedHandoffTest', 'test_e2e_factory_inbox.InboxE2E'}


class ProfileCatalogTest(unittest.TestCase):
    def test_shipped_cases_are_partitioned_without_dropped_or_duplicate_coverage(self):
        cases = set()
        for module in (KIT / 'tests').glob('test_*.py'):
            for group in ast.parse(module.read_text()).body:
                if isinstance(group, ast.ClassDef):
                    cases.update(f'{module.stem}.{group.name}.{method.name}' for method in group.body
                                 if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test_'))
        expected_linux = {case for case in cases if case.rsplit('.', 1)[0] in LINUX_CLASSES}
        coverage = profiles.coverage(KIT)
        self.assertEqual(len(expected_linux), 13)
        self.assertEqual(coverage['linux-security'], expected_linux)
        self.assertEqual(coverage['native'], cases - expected_linux)
        self.assertIn('test_e2e_factory_run.FactoryRunE2E.test_path_decoy_is_never_executed_and_approved_executable_is_bound',
                      coverage['native'])
        self.assertIn('test_native_factory_inbox.NativeInboxTest.test_invalid_event_binding_delivers_nothing_then_valid_record_delivers_once',
                      coverage['native'])

    def test_new_case_in_selected_group_is_covered_not_ignored(self):
        cases = {'test_a.First.test_old', 'test_a.First.test_new', 'test_b.Linux.test_original'}
        lists = {'native': ('test_a',), 'linux-security': ('test_b.Linux',)}
        self.assertEqual(profiles.classify(cases, lists), {'native': cases - {'test_b.Linux.test_original'},
                                                           'linux-security': {'test_b.Linux.test_original'}})

    def test_overlaps_and_unassigned_classes_fail(self):
        cases = {'test_mix.Native.test_a', 'test_mix.Linux.test_b'}
        with self.assertRaisesRegex(ValueError, 'duplicate coverage: test_mix.Linux.test_b'):
            profiles.classify(cases, {'native': ('test_mix',), 'linux-security': ('test_mix.Linux',)})
        with self.assertRaisesRegex(ValueError, 'unclassified test: test_mix.Native.test_a'):
            profiles.classify(cases, {'native': (), 'linux-security': ('test_mix.Linux',)})


class RelocatedVerifierTest(unittest.TestCase):
    def test_extracted_package_checks_native_inventory_outside_cwd_without_unshare(self):
        dist = distribution.DistributionTest()
        dist.setUp()
        self.addCleanup(dist.doCleanups)
        root = dist.extract(dist.build(KIT)).resolve()
        self.assertNotEqual(root, KIT)
        tools = dist.tmp / 'declared binaries'
        tools.mkdir()
        for name in ('git', 'node'):
            path = shutil.which(name)
            self.assertTrue(path, f'{name} is required')
            (tools / name).symlink_to(path)
        env = clean_env(dist.home) | {'PATH': str(tools)} | {name: os.environ[name] for name, _, _ in profiles.NATIVE_FILES}
        result = subprocess.run([sys.executable, '-B', str(root / 'scripts/verify-suite.py'), '--check'],
                                cwd=dist.cwd, env=env, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Selected profile: native', result.stdout)
        self.assertIn('PASS  coverage:', result.stdout)
        self.assertIn('NOT VERIFIED (linux-security excluded)  test_e2e_factory.RelocatedHandoffTest', result.stdout)
        self.assertIn('NOT VERIFIED (linux-security excluded)  test_e2e_factory_inbox.InboxE2E', result.stdout)
        self.assertEqual(list(dist.home.iterdir()), [])
        self.assertEqual(list(dist.cwd.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
