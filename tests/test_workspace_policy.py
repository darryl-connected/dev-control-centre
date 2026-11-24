"""Mac-portable acceptance: real filesystem, CLI, inbox and Git, fake Pi/Herdr processes.

No real provider, Herdr session, SDK or effective-prompt claim. The Herdr fixture
starts the Pi argument recorder as a separate process in the dispatched worktree.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import test_e2e_factory as distribution
from test_e2e_factory_run import KIT, LoopFixture, git, rewrite
from test_setup import SetupFixture, evidence, file_map, write

WRITER = {"provider": "fixture-lab", "model": "Org/Model-V2:2026", "reasoning": "minimal"}
REVIEWER = {**WRITER, "reasoning": "xhigh"}
COORDINATOR = {"provider": "elsewhere", "model": "Coordinator-1", "reasoning": "low"}
MODEL = "fixture-lab/Org/Model-V2:2026"
CUSTOM = {
    "version": 1, "routes": {"coordinator": COORDINATOR, "writer": WRITER, "reviewer": REVIEWER},
    "attempt_limits": {"writer.initial": {"calls": 3, "minutes": 2},
                       "reviewer.initial": {"calls": 7, "minutes": 6},
                       "writer.repair": {"calls": 11, "minutes": 4},
                       "reviewer.rereview": {"calls": 14, "minutes": 9}},
    "repair_limit": 3,
}

PI = '''import json, os, sys
from pathlib import Path
root = Path(os.environ['DCC_RUN_FIXTURE'])
argv = sys.argv[1:]
with (root / 'pi-processes.jsonl').open('a') as out:
    print(json.dumps({'argv': argv, 'cwd': os.getcwd(), 'agent_dir': os.environ['PI_CODING_AGENT_DIR']}), file=out)
if '--list-models' in argv:
    assert argv == ['--offline', '--no-approve', '--no-extensions', '--no-skills', '--no-context-files', '--list-models']
    assert os.environ['PI_OFFLINE'] == '1'
    print('provider       model               context max-out thinking images')
    print('elsewhere      Coordinator-1       128K    2K      yes      no')
    print('fixture-lab    Org/Model-V2:2026    128K    2K      yes      no')
    print('fixture-lab    plain               128K    2K      no       no')
    print('deepseek       deepseek-flash      128K    2K      no       no')
    print('openai         gpt-6.1-sol         128K    2K      yes      no')
'''

HERDR = '''import json, os, shlex, subprocess, sys
from pathlib import Path
root = Path(os.environ['DCC_RUN_FIXTURE'])
argv = sys.argv[3:]
trace = root / 'herdr-processes.jsonl'
rows = trace.read_text().splitlines() if trace.exists() else []
pane = f'fixture-pane-{len(rows)}'
with trace.open('a') as out:
    print(json.dumps({'argv': argv, 'pane': pane}), file=out)
if argv[:2] in (['workspace', 'create'], ['pane', 'split']):
    print(json.dumps({'pane_id': pane, 'workspace_id': f'ws-{pane}'}))
elif argv[:2] == ['pane', 'run']:
    split = next(r['argv'] for r in map(json.loads, rows) if r['pane'] == argv[2])
    cwd = split[split.index('--cwd') + 1]
    name, value = split[split.index('--env') + 1].split('=', 1)
    subprocess.run(shlex.split(argv[3]), env=os.environ | {name: value}, cwd=cwd, check=True)
    print('{}')
elif argv[:2] == ['agent', 'get']:
    print(json.dumps({'agent': 'pi', 'agent_status': 'idle'}))
elif argv[:2] in (['agent', 'rename'], ['agent', 'prompt'], ['agent', 'wait']):
    print(json.dumps({'pane_id': argv[2], 'status': 'done'}))
else:
    raise SystemExit('unsupported fixture Herdr command')
'''


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class PortableLoop(LoopFixture):
    def __init__(self, test: unittest.TestCase, kit: Path = KIT, *, custom: bool = True):
        super().__init__(test, kit=kit, short_socket_path=False)
        # Never inherit real auth/provider config. The OS processes below are fixtures.
        self.pi_fixture = self.root / 'fake pi'
        self.herdr_fixture = self.root / 'fake herdr'
        write(self.pi_fixture, f'#!{sys.executable}\n' + PI, 0o700)
        write(self.herdr_fixture, f'#!{sys.executable}\n' + HERDR, 0o700)
        self.policy = self.workspace / '.dcc/policy.json'
        self.log: list[dict] = []
        self.maps: dict = {}
        test.addCleanup(self.retain)
        if custom:
            write(self.policy, json.dumps(CUSTOM))
            self.manifest['writer']['model'] = MODEL
            rewrite(self.manifest_file, self.manifest, 0o600)
            rewrite(self.brief, self.cli('scripts/factory-job.py', 'render', self.manifest_file, check=True).stdout.encode())

    def retain(self) -> None:
        evidence(self.test._testMethodName + '-policy', {'fixture': str(self.root), 'cli': self.log, 'maps': self.maps,
                 'pi_processes': self.pi_rows(), 'herdr_processes': self.herdr_rows()})

    def cli(self, script, *args, **kwargs):
        result = super().cli(script, *args, **kwargs)
        if hasattr(self, 'log'):
            self.log.append({'script': script, 'argv': list(map(str, args)), 'exit': result.returncode,
                             'stdout': result.stdout, 'stderr': result.stderr})
        return result

    def preview(self, *extra, check=True):
        return super().preview(*extra, check=check, pi=self.pi_fixture, herdr=self.herdr_fixture, fixture_extension=False)

    def launch(self, *, check=True):
        return self.loop('launch', self.plan, '--state', self.state, '--approve', check=check)

    def advance(self, *args, check=True):
        return self.loop('advance', self.state, *args, check=check)

    def pi_rows(self):
        return jsonl(self.root / 'pi-processes.jsonl')

    def herdr_rows(self):
        return jsonl(self.root / 'herdr-processes.jsonl')

    def dispatches(self):
        return [row for row in self.pi_rows() if '--list-models' not in row['argv']]

    def reviewed(self, reviewer_model=MODEL):
        self.register()
        self.preview()
        self.launch()
        write(self.writer / 'new.txt', 'reviewed fixture change\n', 0o644)
        self.publish('writer', 'a1', 'reported')
        self.advance()
        review = Path(self.state_row()['review_tree'])
        self.publish('reviewer', 'a1', 'approved', reviewer_model=reviewer_model)
        return review


class WorkspacePolicyTest(unittest.TestCase):
    def refused(self, result, detail: str, *, code: int = 1):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertIn(detail, result.stderr or result.stdout)

    def assert_process_route(self, row: dict, *, reasoning: str, worktree: Path, agent: Path, role: str):
        argv = row['argv']
        self.assertEqual(argv[argv.index('--model') + 1], MODEL)
        self.assertEqual(argv[argv.index('--thinking') + 1], reasoning)
        self.assertEqual(row['cwd'], str(worktree))
        self.assertEqual(row['agent_dir'], str(agent))
        self.assertIn(f'dcc-{role}-', argv[argv.index('--session-id') + 1])

    def test_defaults_are_literal_and_absent_policy_is_not_a_ceiling(self):
        r = PortableLoop(self, custom=False)
        r.register()
        before = file_map(r.repo)
        r.preview()
        plan = json.loads(r.plan.read_text())
        self.assertEqual(plan['routes'], {
            'coordinator': {'provider': 'openai', 'model': 'gpt-6.1-sol', 'reasoning': 'high'},
            'writer': {'provider': 'deepseek', 'model': 'deepseek-flash', 'reasoning': 'model-default'},
            'reviewer': {'provider': 'openai', 'model': 'gpt-6.1-sol', 'reasoning': 'high'},
        })
        self.assertEqual(plan['attempt_limits'], {
            'writer.initial': {'calls': 60, 'minutes': 25}, 'reviewer.initial': {'calls': 60, 'minutes': 25},
            'writer.repair': {'calls': 30, 'minutes': 15}, 'reviewer.rereview': {'calls': 40, 'minutes': 20},
        })
        self.assertEqual(plan['repair_limit'], 2)
        self.assertEqual(plan['policy_source'], {'source': None, 'sha256': None})
        self.assertIsNone(plan['overall_limit'])
        self.assertFalse(r.state.exists() or r.writer.exists() or r.policy.exists())
        self.assertEqual(r.pi_rows(), [])
        self.assertEqual(file_map(r.repo), before)
        r.maps.update(before_preview=before, after_preview=file_map(r.repo))
        r.launch()
        writer = r.dispatches()[0]
        self.assertIn('deepseek/deepseek-flash', writer['argv'])
        self.assertNotIn('--thinking', writer['argv'])

    def test_selected_same_model_routes_are_separately_dispatched_and_exact_candidate_stages_only(self):
        r = PortableLoop(self)
        review = r.reviewed()
        state = r.state_row()
        self.assertEqual(state['routes'], CUSTOM['routes'])
        self.assertEqual(state['routes']['coordinator'], COORDINATOR)
        writer, reviewer = r.dispatches()
        self.assert_process_route(writer, reasoning='minimal', worktree=r.writer, agent=r.agent, role='writer')
        self.assert_process_route(reviewer, reasoning='xhigh', worktree=review, agent=r.agent, role='reviewer')
        self.assertNotEqual(writer['argv'][writer['argv'].index('--session-id') + 1],
                            reviewer['argv'][reviewer['argv'].index('--session-id') + 1])
        self.assertNotEqual(r.writer, review)
        self.assertEqual((review / 'new.txt').read_bytes(), (r.writer / 'new.txt').read_bytes())
        self.assertEqual(json.loads(r.advance().stdout)['status'], 'ready-to-handoff')
        report = r.inbox / 'reviewer.a1/records/report'
        target = file_map(r.repo)
        agent, home = file_map(r.agent), file_map(r.home)
        r.cli('scripts/factory-job.py', 'integration', r.manifest_file, '--candidate', r.writer,
              '--review', report, '--json', check=True)
        self.assertEqual(file_map(r.repo), target)
        self.refused(r.loop('handoff', r.state), 'approval-required')
        self.assertEqual(file_map(r.repo), target)
        result = json.loads(r.loop('handoff', r.state, '--approve', check=True).stdout)
        self.assertEqual(result['paths'], ['new.txt'])
        self.assertTrue(result['staged_only'])
        self.assertFalse(result['committed'])
        self.assertEqual((r.repo / 'new.txt').read_bytes(), b'reviewed fixture change\n')
        self.assertEqual(r.target_status(), ['A  new.txt'])
        self.assertEqual(git(r.repo, 'rev-parse', 'HEAD').strip(), r.manifest['base']['commit'])
        self.assertEqual(file_map(r.agent), agent)
        self.assertEqual(file_map(r.home), home)
        r.maps.update(target_before_gate=target, target_after_handoff=file_map(r.repo), agent=agent, home=home)

    def test_invalid_and_unavailable_routes_refuse_without_dispatch(self):
        r = PortableLoop(self)
        r.register()
        for content, error in (({'version': True}, 'policy.version'),
                               ({'version': 1, 'api_key': 'never a real value'}, 'unknown fields'),
                               ({'version': 1, 'repair_limit': -1}, 'policy.repair_limit'),
                               ({**CUSTOM, 'attempt_limits': {'writer.initial': {'calls': True, 'minutes': 4}}}, 'positive integer'),
                               ({**CUSTOM, 'routes': {**CUSTOM['routes'], 'reviewer': {**REVIEWER, 'reasoning': 'huge'}}}, 'routes.reviewer.reasoning'),
                               ({**CUSTOM, 'routes': {**CUSTOM['routes'], 'reviewer': {**REVIEWER, 'model': 'Model*'}}}, 'exact provider/model'),
                               ({**CUSTOM, 'routes': {**CUSTOM['routes'], 'writer': {**WRITER, 'model': 'Other'}}}, 'manifest writer must match')):
            with self.subTest(error=error):
                write(r.policy, json.dumps(content))
                before = file_map(r.repo)
                self.refused(r.preview(check=False), error)
                self.assertFalse(r.plan.exists() or r.state.exists() or r.writer.exists())
                self.assertEqual(file_map(r.repo), before)
        for model, error in (('Org/Model-v2:2026', 'unavailable-route'), ('plain', 'unavailable-reasoning')):
            with self.subTest(model=model):
                write(r.policy, json.dumps({**CUSTOM, 'routes': {**CUSTOM['routes'], 'reviewer': {**REVIEWER, 'model': model}}}))
                r.plan = r.state_dir / f'{error}.json'
                r.preview()
                before = file_map(r.repo)
                result = r.launch(check=False)
                self.refused(result, error)
                self.assertIn(f'reviewer fixture-lab/{model}', result.stderr)
                self.assertFalse(r.state.exists() or r.writer.exists())
                self.assertEqual(r.herdr_rows(), [])
                self.assertEqual(r.dispatches(), [])
                self.assertEqual(file_map(r.repo), before)

    def test_three_repairs_and_frozen_limits_with_same_attempt_conserved(self):
        r = PortableLoop(self)
        r.register()
        r.preview()
        plan_bytes = r.plan.read_bytes()
        plan = json.loads(plan_bytes)
        digest = hashlib.sha256(json.dumps(CUSTOM, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(plan['policy_digest'], digest)
        self.assertEqual(plan['policy_source'], {'source': str(r.policy), 'sha256': hashlib.sha256(r.policy.read_bytes()).hexdigest()})
        self.assertEqual(plan['attempt_limits'], CUSTOM['attempt_limits'])
        self.assertEqual(plan['repair_limit'], 3)
        self.assertIsNone(plan['overall_limit'])
        r.launch()
        launch = r.state_row()
        for delta, expected in (('2:1', {'calls': 2, 'minutes': 1}), ('1:1', {'calls': 3, 'minutes': 2}),
                                ('1:1', {'calls': 4, 'minutes': 3})):
            changed = {**CUSTOM, 'repair_limit': 0, 'attempt_limits': {'writer.initial': {'calls': 99, 'minutes': 99}},
                       'routes': {**CUSTOM['routes'], 'reviewer': {**REVIEWER, 'reasoning': 'off'}}}
            write(r.policy, json.dumps(changed))
            self.refused(r.advance('--spend', f'writer.a1:{delta}', check=False), 'no-completion')
            state = r.state_row()
            self.assertEqual(state['attempt_usage']['writer.a1'], expected)
            self.assertEqual(state['usage']['writer'], expected)
            self.assertEqual(state['usage']['shared'], expected)
            self.assertEqual(state['attempt_allocations']['writer.a1'], {'calls': 3, 'minutes': 2})
            self.assertEqual(state['policy_digest'], digest)
            self.assertEqual(state['routes'], CUSTOM['routes'])
            self.assertEqual(state['repair_limit'], 3)
            self.assertEqual(len(r.dispatches()), 1)
        r.policy.unlink()
        r.maps.update(launch=launch, resume=r.state_row())
        for index in range(1, 5):
            attempt = f'a{index}'
            write(r.writer / 'new.txt', f'candidate version {index}\n', 0o644)
            r.publish('writer', attempt, 'reported')
            observed = json.loads(r.advance().stdout)
            self.assertEqual(observed['attempt'], attempt)
            state = r.state_row()
            self.assertEqual(state['attempt_allocations'][f'reviewer.{attempt}'],
                             {'calls': 7, 'minutes': 6} if index == 1 else {'calls': 14, 'minutes': 9})
            self.assertEqual(Path(state['review_tree']).joinpath('new.txt').read_text(), f'candidate version {index}\n')
            self.assert_process_route(r.dispatches()[-1], reasoning='xhigh', worktree=Path(state['review_tree']),
                                      agent=r.agent, role='reviewer')
            r.publish('reviewer', attempt, 'changes_requested', reviewer_model=MODEL)
            count = len(r.dispatches())
            result = r.advance(check=False)
            if index < 4:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['attempt'], f'a{index + 1}')
                self.assertEqual(r.state_row()['attempt_allocations'][f'writer.a{index + 1}'], {'calls': 11, 'minutes': 4})
                self.assertEqual(len(r.dispatches()), count + 1)
            else:
                self.refused(result, 'all 3 approved repair allowances are used')
                self.assertEqual(len(r.dispatches()), count)
        self.assertEqual(r.state_row()['repairs'], 3)
        self.assertEqual(r.state_row()['attempt_usage']['writer.a1'], {'calls': 4, 'minutes': 3})
        self.assertEqual(r.plan.read_bytes(), plan_bytes)
        self.assertEqual(r.target_status(), [])
        r.maps['stopped'] = r.state_row()

        new = PortableLoop(self)
        write(new.policy, json.dumps(changed))
        new.register()
        new.preview()
        new_plan = json.loads(new.plan.read_text())
        self.assertEqual(new_plan['attempt_limits']['writer.initial'], {'calls': 99, 'minutes': 99})
        self.assertEqual(new_plan['routes']['reviewer']['reasoning'], 'off')
        self.assertEqual(new_plan['repair_limit'], 0)
        self.assertNotEqual(new_plan['policy_digest'], digest)

    def test_exhausted_overall_stops_before_reviewer_worktree_or_process(self):
        r = PortableLoop(self)
        r.register()
        r.preview('--overall-limit', '3:2')
        r.launch()
        write(r.writer / 'new.txt', 'candidate\n', 0o644)
        r.publish('writer', 'a1', 'reported')
        before = file_map(r.repo)
        self.refused(r.advance('--spend', 'writer.a1:3:2', check=False), 'selected overall ceiling is exhausted')
        self.assertEqual(file_map(r.repo), before)
        self.assertEqual(r.state_row()['blocked']['scope'], 'overall')
        self.assertEqual(r.state_row()['attempt_usage']['writer.a1'], {'calls': 3, 'minutes': 2})
        self.assertFalse(Path(f'{r.reviewer}-r1').exists())
        self.assertFalse((r.inbox / 'reviewer.a1').exists())
        self.assertEqual(len(r.dispatches()), 1)
        r.maps.update(target_before=before, target_after=file_map(r.repo))

    def test_configured_attempt_allowance_controls_actual_reviewer_dispatch(self):
        for calls, minutes, expected in ((6, 5, True), (7, 6, False), (8, 7, False)):
            with self.subTest(calls=calls, minutes=minutes):
                r = PortableLoop(self)
                r.register()
                r.preview()
                r.launch()
                write(r.writer / 'new.txt', 'candidate\n', 0o644)
                r.publish('writer', 'a1', 'reported')
                # Reproduce a retry of the same allocated attempt after a local missing executable.
                r.pi_fixture.chmod(0o600)
                self.refused(r.advance(check=False), 'missing-tool')
                r.pi_fixture.chmod(0o700)
                pending = r.state_row()
                self.assertEqual(pending['attempt_allocations']['reviewer.a1'], {'calls': 7, 'minutes': 6})
                self.assertEqual(pending['attempt_usage']['reviewer.a1'], {'calls': 0, 'minutes': 0})
                self.assertFalse((r.inbox / 'reviewer.a1').exists())
                before = file_map(r.repo)
                result = r.advance('--spend', f'reviewer.a1:{calls}:{minutes}', check=False)
                final = r.state_row()
                self.assertEqual(final['attempt_usage']['reviewer.a1'], {'calls': calls, 'minutes': minutes})
                if expected:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(len(r.dispatches()), 2)
                    self.assertTrue((r.inbox / 'reviewer.a1').exists())
                else:
                    self.refused(result, 'reviewer.a1 allowance is exhausted')
                    self.assertFalse((r.inbox / 'reviewer.a1').exists())
                    self.assertFalse(Path(f'{r.reviewer}-r1').exists())
                    self.assertEqual(len(r.dispatches()), 1)
                    self.assertEqual(file_map(r.repo), before)
                r.maps.update(before=before, after=file_map(r.repo), pending=pending, final=final)

    def test_modified_or_legacy_active_binding_refuses_without_rewrite(self):
        r = PortableLoop(self)
        r.register()
        r.preview()
        r.launch()
        original = r.state_row()
        for delta, detail in (({'policy': 'attempt-budget-v1'}, 'legacy state'),
                              ({'repair_limit': 99}, 'state no longer matches the approved plan')):
            with self.subTest(delta=delta):
                injected_state = r.state.with_name('injected-state.json')
                rewrite(injected_state, original | delta, 0o400)
                injected_state.replace(r.state)
                before = file_map(r.state_dir)
                self.refused(r.advance(check=False), detail)
                self.assertEqual(file_map(r.state_dir), before)
                self.assertEqual(len(r.dispatches()), 1)

    def test_receipt_wrong_route_refuses_even_with_valid_transport_and_candidate(self):
        r = PortableLoop(self)
        r.reviewed('openai/gpt-6.1-sol')
        target = file_map(r.repo)
        self.refused(r.advance(check=False), 'review-route-mismatch')
        self.refused(r.loop('handoff', r.state, '--approve'), 'no approved reviewer receipt')
        self.assertEqual(file_map(r.repo), target)
        r.maps.update(before=target, after=file_map(r.repo))

    def test_each_independent_integrity_defect_blocks_integration_and_handoff_without_target_mutation(self):
        cases = ('candidate_digest', 'target file contents', 'reviewed files do not match')
        for defect in cases:
            with self.subTest(defect=defect):
                r = PortableLoop(self)
                review = r.reviewed()
                r.advance()
                report = r.inbox / 'reviewer.a1/records/report'
                args = ('integration', r.manifest_file, '--candidate', r.writer, '--review', report, '--json')
                self.assertTrue(json.loads(r.cli('scripts/factory-job.py', *args, check=True).stdout)['ok'])
                if defect == 'candidate_digest':
                    for tree in (r.writer, review):
                        write(tree / 'new.txt', 'both trees now match different bytes\n', 0o644)
                elif defect == 'target file contents':
                    write(r.repo / 'file.txt', 'changed target baseline\n', 0o644)
                else:
                    write(review / 'new.txt', 'only review copy diverges\n', 0o644)
                before = file_map(r.repo)
                gated = r.cli('scripts/factory-job.py', *args)
                self.refused(gated, defect)
                errors = json.loads(gated.stdout)['errors']
                if defect != 'target file contents':
                    self.assertEqual(len(errors), 1, errors)
                handoff = r.loop('handoff', r.state, '--approve')
                self.refused(handoff, 'baseline-drift' if defect == 'target file contents' else defect)
                after = file_map(r.repo)
                self.assertEqual(after, before)
                self.assertFalse((r.repo / 'new.txt').exists())
                self.assertEqual(git(r.repo, 'rev-parse', 'HEAD').strip(), r.manifest['base']['commit'])
                r.maps.update(before=before, after=after, defect=defect)

    def test_relocated_archive_keeps_workspace_edits_separate_from_reviewed_core(self):
        dist = distribution.DistributionTest()
        dist.setUp()
        self.addCleanup(dist.doCleanups)
        archive = dist.build(KIT)
        relocated = dist.extract(archive).resolve()
        self.assertEqual({path for path, entry in file_map(relocated).items() if 'sha256' in entry},
                         distribution.EXPECTED_MEMBERS)
        template = relocated / 'templates/dcc/policy.json'
        self.assertEqual(json.loads(template.read_text())['repair_limit'], 2)
        temp = tempfile.TemporaryDirectory(prefix='dcc-relocated-setup-', dir=os.environ.get('DCC_EVIDENCE'))
        self.addCleanup(temp.cleanup)
        setup = SetupFixture(Path(temp.name).resolve(), relocated)
        append = setup.workspace / '.pi/APPEND_SYSTEM.md'
        write(append, 'my edited workspace instructions\n')
        before = setup.snapshot()
        preview = setup.inspect()
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(setup.snapshot(), before)
        write(setup.plan, preview.stdout)
        self.assertEqual(setup.apply('--approve').returncode, 0)
        self.assertTrue(all(path.startswith(str(relocated)) for path in json.loads(
            (setup.workspace / '.pi/settings.json').read_text())['skills']))
        self.assertEqual(append.read_text(), 'my edited workspace instructions\n')
        r = PortableLoop(self, kit=relocated)
        r.register()
        r.preview()
        self.assertEqual(json.loads(r.plan.read_text())['routes'], CUSTOM['routes'])
        ok = r.cli('scripts/factory-alignment.py', '--json', check=True)
        self.assertTrue(json.loads(ok.stdout)['ok'])
        core = relocated / 'factory/REVIEWER.md'
        core.write_text(core.read_text() + '\nTampered reviewed core fixture.\n')
        prerequisite = r.cli('scripts/factory-alignment.py', '--json')
        self.refused(prerequisite, 'factory/REVIEWER.md')
        self.assertFalse(json.loads(prerequisite.stdout)['ok'])
        r.maps.update(before_setup=before, after_setup=setup.snapshot(), setup_clis=setup.cli_results,
                      archive=str(archive), relocated=str(relocated))


if __name__ == '__main__':
    unittest.main()
