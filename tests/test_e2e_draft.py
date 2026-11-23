"""D1-D3: exercise real B2 records, OpenSpec 1.8.0, target/index and relocated CLI boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from test_e2e_factory import ARCHIVE, EXPECTED_MEMBERS
from test_e2e_prepare import (
    ALIAS,
    AUDIT,
    CHANGE,
    NATIVE,
    WORKFLOW,
    PreparedFixture,
    citations,
    json_write,
    review_packet,
)
from test_factory_job import clean_env
from test_setup import KIT, evidence, write

PROPOSAL = f'{CHANGE}/proposal.md'
DESIGN = f'{CHANGE}/design.md'
TASKS = f'{CHANGE}/tasks.md'
DELTA = f'{CHANGE}/specs/report-export/spec.md'
META = f'{CHANGE}/.openspec.yaml'
BASELINE = 'openspec/specs/report-export/spec.md'
DRAFT = {
    PROPOSAL: '# CSV report export\n\n## Why\nDevelopers need comma-separated reports.\n\n## Scope\nRetention deletion is excluded.\n',
    DESIGN: '# Design\n\nUse the reporting adapter for CSV. Do not change the retention lifecycle.\n',
    TASKS: '# Tasks\n\n## 1. Export\n- [ ] 1.1 Add CSV export.\n- [ ] 1.2 Verify the comma and no deletion.\n',
    DELTA: '## ADDED Requirements\n\n### Requirement: Comma-separated report\nThe report SHALL use a comma delimiter.\n'
           '\n#### Scenario: Selected report\n- **WHEN** the developer exports a report\n- **THEN** CSV uses a comma\n',
}
BASE_SPEC = '# Existing report export\n\n## Purpose\nKeep this current spec.\n\n## Requirements\n\n### Requirement: Report preview\n' \
            'The preview SHALL show the report.\n\n#### Scenario: Owner opens preview\n- **WHEN** an owner opens preview\n- **THEN** the report is visible\n'
TRACE = AUDIT.replace("'env_keys': sorted(values[3] or {})}",
                      "'cwd': os.fsdecode(values[2]) if values[2] is not None else None, 'env_keys': sorted(values[3] or {}), "
                      "'tool_env': {key: (values[3] or {}).get(key) for key in ('OPENSPEC_TELEMETRY', 'DO_NOT_TRACK', 'HOME')}}")


class DraftCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(os.environ.get('DCC_B3_NODE'), 'DCC_B3_NODE is required for real OpenSpec evidence, not a skip')
        self.assertTrue(os.environ.get('DCC_B3_OPENSPEC'), 'DCC_B3_OPENSPEC is required for real OpenSpec evidence, not a skip')
        self.node = str(Path(os.environ['DCC_B3_NODE']).resolve(strict=True))
        self.openspec = str(Path(os.environ['DCC_B3_OPENSPEC']).resolve(strict=True))
        temp = tempfile.TemporaryDirectory(prefix='dcc-b3-', dir=os.environ.get('DCC_EVIDENCE'))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.calls: list[dict] = []
        self.maps: dict = {}
        self.trace = self.root / 'draft-audit.jsonl'
        self.origins = self.root / 'draft-origins.jsonl'
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.author = self.root / 'authored.json'
        self.plan = self.root / 'displayed.json'
        self.addCleanup(self.retain)

    def rows(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def retain(self) -> None:
        fx = getattr(self, 'fx', None)
        evidence(self._testMethodName, {'draft_cli': self.calls, 'b2_cli': [] if fx is None else fx.results,
                                       'audit': self.rows(self.trace), 'origins': self.rows(self.origins), 'maps': self.maps})

    def prepare(self, *, config: str | None = None, kit: Path = KIT, narrowed: bool = True,
                settle: bool = True, cite_workflow: bool = True) -> None:
        self.fx = PreparedFixture(self.root, kit, relocated=kit != KIT)
        target = self.fx.target
        # A changed selected file can keep the same Git status category; hash the current bytes.
        write(target / WORKFLOW, '# OpenSpec workflow\nReview proposal, design, specs and unchecked tasks.\n')
        write(target / 'openspec/changes/archive/archived-change/proposal.md', 'Archive canary\n', 0o640)
        write(target / BASELINE, BASE_SPEC, 0o640)
        write(target / 'openspec/config.yaml', config or 'schema: spec-driven\ncontext: |\n  Reports use the reporting adapter.\n')
        write(target / '.gitignore', f'/{CHANGE}/.openspec.yaml\n')
        self.fx.git_target('add', '-f', BASELINE)
        code, selected = self.fx.inspect(self.fx.selection)
        self.assertEqual(code, 0, selected)
        context = selected['context']
        packet = review_packet(self.fx.selection, context, owner='PM' if narrowed else 'developer',
                               answer=None if narrowed or not settle else '30 days', narrowed='approved' if narrowed else None)
        if narrowed and cite_workflow:
            source = next(item for item in context['sources'] if item['path'] == WORKFLOW)
            packet['review']['scopes']['export-button']['citations'] += citations(source, 2, 2)
        code, inspected = self.fx.inspect(packet)
        self.assertEqual(code, 0, inspected)
        code, saved = self.fx.save(inspected)
        self.assertEqual(code, 0, saved)
        self.assertEqual(saved['record']['assessment']['state'], 'ready_for_drafting' if settle else 'blocked')
        self.saved = saved
        json_write(self.author, {'version': 1, 'artifacts': DRAFT})

    def snapshot(self, label: str) -> dict:
        out = self.fx.snapshot() | {'target_index_hex': (self.fx.target / '.git/index').read_bytes().hex()}
        self.maps[label] = out
        return out

    def cli(self, *args: str) -> tuple[int, dict]:
        program = self.fx.kit / 'scripts/draft.py'
        argv = [sys.executable, '-B', '-S', '-c', TRACE, str(self.trace), str(self.origins), str(program),
                str(KIT) if self.fx.kit != KIT else '', *args]
        env = clean_env(self.fx.h.fx.home) | {'TMPDIR': str(self.scratch), 'GIT_DIR': '/invalid-ambient-override',
                                             'CLICKUP_TOKEN': 'synthetic-canary-not-for-child', 'OPENSPEC_TELEMETRY': '1'}
        result = subprocess.run(argv, cwd=self.root, env=env, capture_output=True, text=True, check=False, timeout=45)
        self.calls.append({'program': str(program), 'args': args, 'exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        output = json.loads(result.stdout or result.stderr)
        self.assertIs(output['launch_authority'], False)
        self.assertIn('No content sign-off, implementation or factory launch authority.', output['authority'])
        return result.returncode, output

    def preview(self, *, openspec: str | None = None, change: str = 'export-reports') -> tuple[int, dict]:
        return self.cli('preview', '--workspace', str(self.fx.workspace), '--repo', ALIAS, '--task', NATIVE,
                        '--change', change, '--draft', str(self.author), '--openspec', openspec or self.openspec, '--node', self.node)

    def apply(self, preview: dict, *, approve: bool = True, token: str | None = None) -> tuple[int, dict]:
        json_write(self.plan, preview)
        return self.cli('apply', '--plan', str(self.plan), *(['--approve', token or preview['approval_sha256']] if approve else []))

    def refused(self, result: tuple[int, dict], before: dict, label: str, code: str) -> dict:
        self.assertEqual(self.snapshot(label), before, f'{label}: a refused operation changed target/index or unrelated inputs')
        status, output = result
        self.assertEqual(status, 2, f'{label}: expected refusal, observed {output.get("result", output.get("plan", {}).get("artifacts"))}')
        self.assertEqual(output['error']['code'], code, f'{label}: wrong guard or tool failure: {output}')
        return output['error']

    def assert_preview(self, preview: dict) -> None:
        plan = preview['plan']
        expected = DRAFT | {META: plan['artifacts'][META]}
        self.assertRegex(expected[META], r'\Aschema: spec-driven\ncreated: \d{4}-\d{2}-\d{2}\n\Z')
        self.assertEqual(plan['artifacts'], expected)
        self.assertRegex(preview['approval_sha256'], r'^[a-f0-9]{64}$')
        self.assertEqual(preview['validation'], 'not run in preview')
        self.assertEqual(plan['request']['task'], NATIVE)
        self.assertEqual(plan['request']['repo'], ALIAS)
        provenance = plan['provenance']
        self.assertEqual(provenance['revision'], self.saved['revision'])
        self.assertEqual(provenance['preparation'], self.saved['record'])
        self.assertEqual(provenance['preparation']['target_root'], str(self.fx.target))
        assessment = provenance['preparation']['assessment']
        self.assertEqual(assessment['active_scope'], 'export-button')
        self.assertEqual(assessment['decisions']['delimiter']['value'], 'comma')
        self.assertEqual(assessment['excluded_scopes'], ['retention-deletion'])
        self.assertIn('retention-deletion', assessment['exclusions'])
        cites = assessment['scopes']['export-button']['citations']
        self.assertTrue(any(item['source'].startswith('hub:') and item['line'] == 7 for item in cites))
        workflow_bytes = b'# OpenSpec workflow\nReview proposal, design, specs and unchecked tasks.\n'
        self.assertIn({'source': f'target:{WORKFLOW}', 'sha256': hashlib.sha256(workflow_bytes).hexdigest(),
                       'line': 2, 'end_line': 2, 'excerpt': 'Review proposal, design, specs and unchecked tasks.',
                       'excerpt_shortened': False}, cites)
        self.assertEqual(plan['discovery']['version'], '1.8.0')
        self.assertEqual(plan['discovery']['schema'], 'spec-driven')
        self.assertEqual(plan['discovery']['output_paths'], {'proposal': PROPOSAL, 'design': DESIGN, 'tasks': TASKS,
                                                             'specs': f'{CHANGE}/specs/**/*.md'})
        self.assertEqual({item['id']: item['requires'] for item in plan['discovery']['artifacts']},
                         {'proposal': [], 'design': ['proposal'], 'specs': ['proposal'], 'tasks': ['specs', 'design']})

    def test_g1_preview_and_refusal_preserve_exact_bytes_and_index(self) -> None:
        self.prepare()
        before = self.snapshot('before-preview')
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        self.assertEqual(self.snapshot('after-preview'), before)
        self.assert_preview(preview)
        rows = self.rows(self.trace)
        self.refused(self.apply(preview, approve=False), before, 'without-approval', 'approval_required')
        self.assertEqual(self.rows(self.trace), rows, 'no subprocess should run without approval')

    def test_g1_changed_cited_source_refuses_even_when_git_status_looks_same(self) -> None:
        self.prepare()
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        write(self.fx.target / WORKFLOW, '# OpenSpec workflow\nReplacement rule; review again.\n')
        before = self.snapshot('changed-cited-source')
        self.refused(self.apply(preview), before, 'after-cited-source-refusal', 'stale_preparation')

    def test_g1_changed_authored_input_and_wrong_approval_leave_target_alone(self) -> None:
        self.prepare()
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        before = self.snapshot('before-author-drift')
        self.refused(self.apply(preview, token='0' * 64), before, 'wrong-approval', 'approval_mismatch')
        json_write(self.author, {'version': 1, 'artifacts': DRAFT | {PROPOSAL: '# Changed, approved bytes no longer current\n'}})
        self.refused(self.apply(preview), before, 'after-author-drift', 'stale_plan')

    def test_g1_blocked_or_unreviewed_scope_is_not_a_draft(self) -> None:
        self.prepare(narrowed=False, settle=False)
        before = self.snapshot('blocked-scope')
        self.refused(self.preview(), before, 'after-blocked-scope', 'scope_not_ready')

    def test_g2_existing_change_is_not_replaced_or_reported_as_new(self) -> None:
        self.prepare()
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        # This metadata-only existing draft is intentionally invisible to B2's artifact
        # inventory and Git status; the independent filesystem collision must catch it.
        write(self.fx.target / META, 'schema: spec-driven\ncreated: 2023-01-02\n', 0o640)
        before = self.snapshot('existing-change-with-preserved-metadata')
        for label, action in (('preview-existing', self.preview), ('apply-existing', lambda: self.apply(preview))):
            with self.subTest(label=label):
                refused = self.refused(action(), before, label, 'change_exists')
                self.assertEqual(refused.get('path'), str(self.fx.target / CHANGE), 'the existing directory must be reported')

    def test_g2_wrong_outside_destination_is_never_a_planned_artifact(self) -> None:
        self.prepare()
        outside = 'openspec/changes/separate-change/proposal.md'
        fixture = {name: text for name, text in DRAFT.items() if name != PROPOSAL}
        json_write(self.author, {'version': 1, 'artifacts': fixture | {outside: DRAFT[PROPOSAL]}})
        before = self.snapshot('before-outside-path')
        diagnostic = self.refused(self.preview(), before, 'outside-path', 'out_of_scope')
        self.assertEqual(diagnostic.get('path'), outside)
        self.assertFalse((self.fx.target / outside).exists())

    def test_g2_config_drift_wrong_change_and_missing_cli_are_not_success(self) -> None:
        self.prepare()
        initial = self.snapshot('before-tool-refusals')
        self.refused(self.preview(openspec=str(self.root / 'missing-openspec')), initial, 'missing-tool', 'tool_unavailable')
        self.refused(self.preview(change='different-change'), initial, 'wrong-change', 'wrong_change')
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        write(self.fx.target / 'openspec/config.yaml', 'schema: spec-driven\ncontext: changed\n')
        changed = self.snapshot('changed-config')
        self.refused(self.apply(preview), changed, 'config-drift', 'stale_preparation')

    def test_g2_unsupported_config_is_not_projected_as_spec_driven(self) -> None:
        self.prepare(config='schema: custom-workspace\n')
        before = self.snapshot('before-unsupported-config')
        self.refused(self.preview(), before, 'unsupported-config', 'unsupported_layout')

    def test_g2_unreviewed_target_workflow_is_a_blocker(self) -> None:
        self.prepare(cite_workflow=False)
        before = self.snapshot('before-unreviewed-workflow')
        self.refused(self.preview(), before, 'unreviewed-workflow', 'workflow_unreviewed')

    def test_g3_real_invalid_spec_verdict_cannot_publish(self) -> None:
        self.prepare()
        invalid = DRAFT[DELTA].split('#### Scenario:')[0]
        json_write(self.author, {'version': 1, 'artifacts': DRAFT | {DELTA: invalid}})
        before = self.snapshot('before-invalid')
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        self.assertEqual(preview['plan']['artifacts'][DELTA], invalid)
        result = self.apply(preview)
        error = self.refused(result, before, 'after-invalid', 'validation_failed')
        validation = error['validation']
        self.assertEqual(validation['exit'], 1)
        self.assertEqual(validation['argv'], [self.node, self.openspec, 'validate', 'export-reports', '--type', 'change',
                                              '--strict', '--json', '--no-interactive'])
        report = validation['report']
        self.assertEqual(report['summary']['totals'], {'items': 1, 'passed': 0, 'failed': 1})
        self.assertIs(report['items'][0]['valid'], False)
        self.assertTrue(any('at least one scenario' in row['message'] for row in report['items'][0]['issues']))

    def test_g3_only_exact_displayed_bytes_may_be_published(self) -> None:
        self.prepare()
        before = self.snapshot('before-exact-plan')
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        preview['plan']['artifacts'][PROPOSAL] = '# Forged displayed content\n'
        # An operator assertion can approve this altered document, but it no longer
        # matches the authored input/discovered bytes. No undisplayed bytes may land.
        canonical = (json.dumps(preview['plan'], indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
        self.refused(self.apply(preview, token=hashlib.sha256(canonical).hexdigest()), before,
                     'altered-plan-with-new-approval', 'stale_plan')

    def success(self) -> None:
        before = self.snapshot('before-success')
        status, preview = self.preview()
        self.assertEqual(status, 0, preview)
        self.assertEqual(self.snapshot('success-preview-only'), before)
        self.assert_preview(preview)
        status, result = self.apply(preview)
        self.assertEqual(status, 0, result)
        after = self.snapshot('after-success')
        new = set(after['repo']) - set(before['repo'])
        expected_files = set(DRAFT) | {META}
        self.assertEqual(new, expected_files | {CHANGE, f'{CHANGE}/specs', f'{CHANGE}/specs/report-export'})
        self.assertEqual(before, after | {'repo': {key: value for key, value in after['repo'].items() if key not in new}})
        for name, content in preview['plan']['artifacts'].items():
            raw = (self.fx.target / name).read_bytes()
            self.assertEqual(raw, content.encode('utf-8'), name)
            self.assertEqual(result['artifacts'][name], hashlib.sha256(raw).hexdigest(), name)
        actual_tasks = (self.fx.target / TASKS).read_text()
        self.assertEqual(re.findall(r'\[.\]', actual_tasks), ['[ ]', '[ ]'])
        self.assertEqual(result['result'], 'draft_created')
        self.assertEqual(result['scope'], 'export-button')
        self.assertEqual(result['approval_sha256'], preview['approval_sha256'])
        self.assertIn('Review the exact repository artifacts', result['next_step'])
        validation = result['validation']
        command = ['validate', 'export-reports', '--type', 'change', '--strict', '--json', '--no-interactive']
        self.assertEqual(validation['argv'], [self.node, self.openspec, *command])
        self.assertEqual(validation['exit'], 0)
        self.assertEqual(validation['report']['summary']['totals'], {'items': 1, 'passed': 1, 'failed': 0})
        self.assertIs(validation['report']['items'][0]['valid'], True)
        self.assertEqual(validation['report']['items'][0]['id'], 'export-reports')
        tools = []
        for row in self.rows(self.trace):
            self.assertNotIn('forbidden', row)
            if 'argv' not in row:
                continue
            if row['exe'] == self.node:
                self.assertEqual(row['argv'][:2], [self.node, self.openspec])
                self.assertTrue(Path(row['cwd']).is_relative_to(self.scratch))
                self.assertFalse(Path(row['cwd']).is_relative_to(self.fx.target))
                self.assertEqual(row['tool_env']['HOME'], str(Path(row['cwd']) / 'private-home'))
                self.assertEqual(row['tool_env']['OPENSPEC_TELEMETRY'], '0')
                self.assertEqual(row['tool_env']['DO_NOT_TRACK'], '1')
                tools.append(row['argv'][2:])
            else:
                self.assertEqual(row['exe'], self.fx.h.git_path)
                self.assertIn('--no-optional-locks', row['argv'])
            self.assertNotIn('CLICKUP_TOKEN', row['env_keys'])
            self.assertNotIn('GIT_DIR', row['env_keys'])
        discovery = [['--version'], ['new', 'change', 'export-reports', '--json'],
                     ['status', '--change', 'export-reports', '--json']]
        self.assertEqual(tools, discovery * 2 + [command])

    def test_g3_success_only_changes_displayed_artifacts(self) -> None:
        self.prepare()
        self.success()

    def test_g3_relocated_package_invokes_its_own_draft_and_real_validator(self) -> None:
        output = self.root / 'distribution'
        result = subprocess.run([sys.executable, '-B', str(KIT / 'scripts/build.py'), '--output', str(output)],
                                cwd=self.root, env=clean_env(self.root), capture_output=True, text=True, check=False, timeout=20)
        self.calls.append({'build_exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        self.assertEqual(result.returncode, 0, result.stderr)
        kit = self.root / 'relocated kit'
        with tarfile.open(output / ARCHIVE, 'r:gz') as archive:
            self.assertEqual(set(archive.getnames()), EXPECTED_MEMBERS)
            archive.extractall(kit, filter='data')
        self.prepare(kit=kit)
        self.success()
        filenames = {file for row in self.rows(self.origins) for file in row['executed']}
        self.assertLessEqual({str(kit / name) for name in ('scripts/draft.py', 'scripts/lib/openspec_draft.py',
                                                          'scripts/lib/task_preparation.py')}, filenames)
        self.assertFalse(any(Path(file).is_relative_to(KIT) for file in filenames))
