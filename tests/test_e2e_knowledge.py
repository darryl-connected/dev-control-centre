"""Relocated public archive, approved mapping, fresh-process lookup and readiness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import unittest
from pathlib import Path

from test_e2e_factory import ARCHIVE, EXPECTED_MEMBERS
from test_factory_job import clean_env
from test_knowledge import (
    EXPORT,
    ORIGIN_AUDIT,
    HubFixture,
    assert_git_boundary,
    assert_index,
)
from test_setup import KIT, evidence, write

AUDITED_SETUP = ORIGIN_AUDIT + r'''
import runpy
trace, script, *args = sys.argv[1:]
watch_origins(trace, script, args)
sys.argv = [script, *args]
sys.path.insert(0, os.path.dirname(script))
runpy.run_path(script, run_name='__main__')
'''


class KnowledgeDistributionTest(unittest.TestCase):
    def assert_relocated_origins(self, kit: Path, records: list[dict]) -> None:
        setup = str(kit / 'scripts/setup.py')
        knowledge = str(kit / 'scripts/knowledge.py')
        helper = str(kit / 'scripts/lib/knowledge_hub.py')
        self.assertEqual([(row['script'], row['args'][0]) for row in records], [
            (setup, 'inspect'), (knowledge, 'inspect'), (knowledge, 'apply'),
            (setup, 'inspect'), (knowledge, 'sources'), (setup, 'inspect'),
            (knowledge, 'sources'), (setup, 'inspect'),
        ])
        stdlib = {Path(sysconfig.get_path(key)).resolve() for key in ('stdlib', 'platstdlib')}
        for row in records:
            with self.subTest(script=row['script'], args=row['args']):
                for event in ('code_reads', 'executed'):
                    outside = []
                    for origin in map(Path, row[event]):
                        bundled = origin.is_relative_to(kit) and origin.relative_to(kit).as_posix() in EXPECTED_MEMBERS
                        standard = (origin.name not in {'knowledge.py', 'knowledge_hub.py', 'setup.py'}
                                    and not {'site-packages', 'dist-packages'}.intersection(origin.parts)
                                    and any(origin.is_relative_to(library) for library in stdlib))
                        if not (bundled or standard):
                            outside.append(str(origin))
                    self.assertEqual(outside, [], f'relocated helper origin: unexpected Python {event} outside the archive or stdlib')
                    required = {setup, helper, row['script']}
                    self.assertLessEqual(required, set(row[event]), f'relocated helper origin: missing shipped Python {event}')

    def test_relocated_cli_and_optional_readiness_report_actual_boundaries(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix='dcc-knowledge-e2e-', dir=os.environ.get('DCC_EVIDENCE'))
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        kit = root / 'relocated kit'
        kit.mkdir()
        build = root / 'dist'
        built = subprocess.run([sys.executable, '-B', str(KIT / 'scripts/build.py'), '--output', str(build)],
                               cwd=root, env=clean_env(root), capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(built.returncode, 0, built.stderr)
        with tarfile.open(build / ARCHIVE, 'r:gz') as archive:
            self.assertCountEqual(archive.getnames(), EXPECTED_MEMBERS)
            for member in archive.getmembers():
                target = kit / member.name
                self.assertTrue(member.isfile() and target.resolve().is_relative_to(kit))
                data = archive.extractfile(member)
                assert data is not None
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.read())
        origin_trace = root / 'relocated-origins.jsonl'
        h = HubFixture(root, kit, origin_trace=origin_trace)
        self.addCleanup(assert_git_boundary, self, h)
        observed_bin = root / 'observe-bin'
        observed_bin.mkdir()
        (observed_bin / 'git').symlink_to(h.git_path)
        for name in ('pi', 'herdr'):
            (observed_bin / name).symlink_to(h.fx.bin / name)
        readiness = []

        def observe(expected: str) -> None:
            result = subprocess.run([sys.executable, '-B', '-S', '-c', AUDITED_SETUP, str(origin_trace),
                                     str(kit / 'scripts/setup.py'), 'inspect', '--workspace', str(h.workspace)], cwd=root,
                                    env=clean_env(h.fx.home) | {'PATH': str(observed_bin)}, capture_output=True,
                                    text=True, check=False, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = json.loads(result.stdout)['readiness']
            readiness.append(actual)
            self.assertEqual(actual['capabilities'], {
                'knowledge_integration': expected,
                'shared_meeting_notes': 'not established; deferred',
                'fathom': 'optional; NOT VERIFIED',
                'clickup': 'standalone read-only reader available; authentication not checked',
                'context_retrieval': 'selected-task preparation available locally; no task assessment observed by setup',
                'live_factory': 'coordinator-invoked loop available locally; live provider and account operation NOT VERIFIED',
                'provider_fallback': 'writer-only switch requires explicit approval; role isolation and accounts NOT VERIFIED',
                'openspec_drafting': 'local draft and strict validation helper available; tool and target workflow not checked by setup',
                'full_task_start': 'blocked: explicit developer launch approval required',
            })
            self.assertEqual(actual['workflow'], 'blocked; registration is not overall workflow readiness or launch permission')
            self.assertEqual(actual['workspace_configuration'], 'configured')

        observe('not configured; optional')
        before = h.snapshot()
        h.configure()
        after_apply = h.snapshot()
        observe('locally mapped; clean checkout observed; no source lookup observed')
        index = assert_index(self, h.lookup(), h.commit)
        self.assertEqual(h.snapshot(), after_apply)
        write(h.source / EXPORT, '# Local dirty edit')
        observe('blocked: dirty_checkout; source checkout has staged, unstaged or untracked changes')
        dirty = h.lookup()
        self.assertEqual(dirty.returncode, 2, dirty.stdout + dirty.stderr)
        self.assertEqual(json.loads(dirty.stderr)['error']['code'], 'dirty_checkout')
        h.source.rename(root / 'parked source')
        observe('blocked: checkout_unavailable; expected a physical Git checkout root with its own .git directory')
        origins = [json.loads(line) for line in origin_trace.read_text(encoding='utf-8').splitlines()]
        evidence('relocated-knowledge', {'members': sorted(EXPECTED_MEMBERS), 'index': index, 'readiness': readiness,
                                        'cli': h.results, 'audit': h.records(), 'runtime_origins': origins,
                                        'before': before, 'after_apply': after_apply})
        self.assert_relocated_origins(kit, origins)


if __name__ == '__main__':
    unittest.main()
