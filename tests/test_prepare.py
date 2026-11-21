"""Structured preparation guards; semantic review is supplied, not inferred by these tests."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from test_setup import KIT

sys.path.insert(0, str(KIT / 'scripts'))
sys.path.insert(0, str(KIT / 'scripts/lib'))
import task_preparation as prep


class PreparationSchemaTest(unittest.TestCase):
    def test_association_only_declared_forms(self) -> None:
        rows: list[dict] = []
        prep.collect_labels('Compared against PRD124; unrelated.', {'field': 'description'}, rows)
        prep.collect_labels('PRD1234 title', {'field': 'name'}, rows, title=True)
        self.assertEqual(rows, [])
        prep.collect_labels('Parent\nPRD: PRD123\nProduct requirements: PRD124', {'field': 'comment'}, rows)
        self.assertEqual([(row['prd'], row['location']['line']) for row in rows], [('PRD123', 2), ('PRD124', 3)])
        for body, title in (('PRD123/PRD124', True), ('PRD: PRD123 / PRD124', False)):
            prep.collect_labels(body, {'field': 'name' if title else 'description'}, rows, title=title)
            self.assertEqual([row['prd'] for row in rows[-2:]], ['PRD123', 'PRD124'])
        chosen = prep.association(rows, {'prd': 'PRD123', 'by': 'Operating developer', 'reason': 'Explicit confirmation'})
        self.assertTrue(chosen['conflict'])
        self.assertEqual(chosen['binding']['from'], 'developer-supplied, not task data')
        self.assertEqual(chosen['candidates'], rows)

    def test_explicit_source_path_rejects_unsafe_names(self) -> None:
        for name in ('..', 'src/../canary', 'src//file', 'src/.git/config', 'src/.env.dev', 'src/token.pem',
                     '/outside', './src/file', 'http:example/file', 'src\\file'):
            with self.subTest(name=name), self.assertRaises(prep.hub.Blocked):
                prep.relative(name)
        self.assertEqual(prep.relative('packages/api export/data.md'), 'packages/api export/data.md')

    def test_citation_requires_matching_hash_and_available_line_range(self) -> None:
        source = {'hub:a.md': {'sha256': 'a' * 64, 'ranges': [{'line': 4, 'end_line': 5, 'text': 'four\nfive'}]}}
        cite = {'source': 'hub:a.md', 'sha256': 'a' * 64, 'line': 4, 'end_line': 5}
        self.assertEqual(prep.citation(cite, source)['excerpt'], 'four\nfive')
        for change in ({'sha256': 'b' * 64}, {'line': 3}, {'end_line': 6}, {'line': True}, {'source': 'target:a.md'}):
            with self.subTest(change=change), self.assertRaisesRegex(prep.hub.Blocked, 'current body hash'):
                prep.citation(cite | change, source)

    def test_body_size_count_and_nontext_bounds_not_reviewable(self) -> None:
        budget = prep.TextBudget()
        for _ in range(128):
            budget.add(b'one', 'fixture')
        with self.assertRaisesRegex(prep.hub.Blocked, 'count or aggregate'):
            budget.add(b'next', 'fixture')
        budget = prep.TextBudget()
        budget.size = 64 * 1024**2
        with self.assertRaisesRegex(prep.hub.Blocked, 'count or aggregate'):
            budget.add(b'next', 'fixture')
        with tempfile.TemporaryDirectory(dir=os.environ.get('DCC_EVIDENCE')) as folder:
            path = Path(folder) / 'fixture'
            path.write_bytes(b'too long')
            with self.assertRaisesRegex(prep.hub.Blocked, 'byte limit'):
                prep.read_regular(path, 2)
        for body in (b'\xff', b'\x00', b'\n'):
            with self.subTest(body=body), self.assertRaises(prep.hub.Blocked):
                prep.decoded(body, 'fixture')

    def test_wrong_task_invalid_intake_or_duplicate_keys(self) -> None:
        path = Path('synthetic-intake.json')
        for value in (None, {}, {'id': 'abc/123'}, {'id': 'abc123', 'name': 'Report'}):
            with self.subTest(value=value), self.assertRaises(prep.hub.Blocked):
                prep.intake_view(json.dumps({'selected': value, 'status': 'observed', 'ancestors': [], 'unresolved': []}).encode(), path)
        with self.assertRaisesRegex(ValueError, 'malformed JSON'):
            prep.intake_view(b'{"selected": {}, "selected": null}', path)
        with self.assertRaisesRegex(prep.hub.Blocked, 'selected native task'):
            prep.selection_input({'version': 1, 'task': 'wrong123'}, 'abc123')