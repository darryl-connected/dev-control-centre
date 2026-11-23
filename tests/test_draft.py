"""Bounded authored-input shape; real workflow guards live in test_e2e_draft."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/lib'))

import openspec_draft as draft

PREFIX = PurePosixPath('openspec/changes/export-reports')


class AuthoredInputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.files = {f'{PREFIX}/proposal.md': 'Proposal with café\r\n', f'{PREFIX}/design.md': '# Design\n',
                      f'{PREFIX}/tasks.md': '- [ ] Do the work\n', f'{PREFIX}/specs/reporting/spec.md': '# Spec\n'}

    def test_preserves_markdown_encoding_and_line_endings(self) -> None:
        self.assertEqual(draft.authored_paths(self.files, PREFIX), {key: value.encode() for key, value in self.files.items()})

    def test_refuses_missing_required_file_and_completed_tasks(self) -> None:
        del self.files[f'{PREFIX}/design.md']
        self.files[f'{PREFIX}/specs/second/spec.md'] = '# Second\n'
        with self.assertRaises(draft.prep.hub.Blocked) as caught:
            draft.authored_paths(self.files, PREFIX)
        self.assertEqual(caught.exception.diagnostic['code'], 'invalid_draft')
        self.files[f'{PREFIX}/design.md'] = '# Design\n'
        self.files[f'{PREFIX}/tasks.md'] += '2. [X] Already completed\n'
        with self.assertRaises(draft.prep.hub.Blocked) as caught:
            draft.authored_paths(self.files, PREFIX)
        self.assertEqual(caught.exception.diagnostic['code'], 'invalid_tasks')

    def test_refuses_traversal_noncanonical_and_scaffold_authorship(self) -> None:
        for extra in (f'{PREFIX}/../proposal.md', f'{PREFIX}//proposal.md', f'{PREFIX}/.openspec.yaml',
                      f'{PREFIX}/specs/multi/area/spec.md'):
            with self.subTest(path=extra), self.assertRaises(draft.prep.hub.Blocked):
                draft.authored_paths(self.files | {extra: 'Not allowed.'}, PREFIX)
