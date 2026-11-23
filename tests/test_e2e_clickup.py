"""Rebuild and relocate the distribution; exercise intake and offline setup."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import sysconfig
import tarfile
import unittest
from pathlib import Path

from test_clickup import (
    COMMENTS,
    CURSOR,
    TASK_PATH,
    ClickUpTest,
    comment,
    comments,
    first_page,
)
from test_e2e_factory import ARCHIVE, EXPECTED_EXECUTABLES, EXPECTED_MEMBERS
from test_factory_job import clean_env, digest
from test_setup import KIT, SetupFixture, file_map

B1_MEMBERS = {
    "docs/clickup.md", "references/clickup-api.md", "scripts/clickup.py", "scripts/lib/clickup_reader.py",
    "tests/test_clickup.py", "tests/test_e2e_clickup.py",
}


class ClickUpDistributionTest(ClickUpTest):
    def relocate(self) -> Path:
        fx = self.fx
        kit = fx.root / "physical relocated kit"
        kit.mkdir()
        output = fx.root / "dist"
        built = subprocess.run([sys.executable, "-B", "-S", str(KIT / "scripts/build.py"), "--output", str(output)],
                               cwd=fx.cwd, env=clean_env(fx.home), text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(built.returncode, 0, built.stderr)
        manifest = {}
        with tarfile.open(output / ARCHIVE, "r:gz") as archive:
            self.assertCountEqual(archive.getnames(), EXPECTED_MEMBERS)
            self.assertLessEqual(B1_MEMBERS, set(archive.getnames()))
            for member in archive.getmembers():
                destination = kit / member.name
                self.assertTrue(member.isfile() and destination.resolve().is_relative_to(kit))
                self.assertEqual(member.mode, 0o755 if member.name in EXPECTED_EXECUTABLES else 0o644)
                data = archive.extractfile(member)
                assert data is not None
                contents = data.read()
                self.assertEqual(contents, (KIT / member.name).read_bytes())
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents)
                destination.chmod(member.mode)
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), member.mode)
                manifest[member.name] = {"sha256": digest(contents), "mode": oct(member.mode)}
        fx.maps["archive"] = manifest
        return kit

    def test_shipped_reader_returns_relocated_context_and_origins(self) -> None:
        fx = self.fx
        kit = self.relocate()
        fx.routes[COMMENTS] = comments(*first_page())
        fx.routes[COMMENTS + CURSOR] = comments(comment("archiveold", 1301, "Relocated source: do not round tax."))
        r = fx.run(kit=kit, denied=KIT)
        selected = self.selected(self.context(r))
        self.assertEqual(selected["comments"][-1]["text"], "Relocated source: do not round tax.")
        self.assertEqual(r.stdout.count("Relocated source: do not round tax."), 1)
        self.assertEqual(fx.routes_seen(), ["/api/v2/task/86fixture1", "/api/v2/task/86fixture1/comment",
                                          "/api/v2/task/86fixture1/comment?start=1976&start_id=note24"])
        observation = fx.results[-1]
        self.assertEqual([row["event"] for row in observation["audit"]], ["original_denied"] + ["https_binding"] * 3)
        rows = observation["origins"]
        self.assertEqual(len(rows), 1)
        library = {Path(sysconfig.get_path(key)).resolve() for key in ("stdlib", "platstdlib")}
        for event in ("code_reads", "executed"):
            origins = set(map(Path, rows[0][event]))
            self.assertLessEqual({kit / "scripts/clickup.py", kit / "scripts/lib/clickup_reader.py"}, origins)
            for origin in origins:
                shipped = origin.is_relative_to(kit) and origin.relative_to(kit).as_posix() in B1_MEMBERS
                standard = (origin.name not in {"clickup.py", "clickup_reader.py"}
                            and not {"site-packages", "dist-packages"}.intersection(origin.parts)
                            and any(origin.is_relative_to(path) for path in library))
                self.assertTrue(shipped or standard, f"unshipped {event}: {origin}")
        self.assertEqual(file_map(fx.home), {})
        self.assertEqual(file_map(fx.cwd), {})

    def test_relocated_setup_stays_blocked_and_never_checks_clickup(self) -> None:
        fx = self.fx
        kit = self.relocate()
        setup_root = fx.root / "separate workspace fixtures"
        setup_root.mkdir()
        setup = SetupFixture(setup_root, kit)
        before = setup.snapshot()
        r = setup.inspect()
        fx.maps["setup"] = {"cli": setup.cli_results, "children": setup.child_commands(), "before": before,
                            "after": setup.snapshot()}
        # SetupFixture audits outbound connects and runs in a fresh, tokenless environment.
        self.assertEqual(fx.provider.trace, [])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        commands = setup.child_commands()
        self.assertTrue(commands)
        self.assertTrue(all(isinstance(argv, list) for argv in commands), f"unexpected setup audit events: {commands}")
        self.assertEqual(setup.snapshot(), before)
        observed = json.loads(r.stdout)["readiness"]
        self.assertEqual(observed["workflow"], "blocked; registration is not overall workflow readiness or launch permission")
        capabilities = observed["capabilities"]
        self.assertEqual(capabilities["clickup"], "standalone read-only reader available; authentication not checked")
        self.assertEqual(capabilities["context_retrieval"], "selected-task preparation available locally; no task assessment observed by setup")
        self.assertEqual(capabilities["openspec_drafting"], "local draft and strict validation helper available; tool and target workflow not checked by setup")
        self.assertEqual(capabilities["full_task_start"], "blocked: explicit developer launch approval required")
        self.assertEqual(capabilities["live_factory"], "coordinator-invoked loop available locally; live provider and account operation NOT VERIFIED")
        for key in ("authenticated_integrations", "fresh_macos_v9_prepared_exercise", "full_macos_v10", "windows_follow_up"):
            self.assertEqual(observed["verification"][key], "NOT VERIFIED")
        self.assertNotIn(TASK_PATH, r.stdout)


if __name__ == "__main__":
    unittest.main()
