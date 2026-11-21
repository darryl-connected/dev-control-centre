"""Document/resource assertions only: no Pi loading or agent behaviour is exercised."""

import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
# A14 independently fixed content expectations. Loading and actual command expansion
# are tested separately; these clauses do not prove that a model follows them.
SKILL_CLAUSES = {
    "setup": (
        "Ask only for missing technical information", "Read accessible configuration first",
        "Do not start a business, identity, voice, or revenue interview",
        "For ordinary setup, do not request a knowledge location or treat its absence as an A14 blocker",
        "Only for an explicit knowledge setup request", "Ask only for the missing local checkout path if needed",
        "Keep the hub read-only: do not update the checkout, run source commands, or follow external links",
        "Shared meeting notes are not established and remain deferred", "Personal Fathom is optional",
        "A trusted project APPEND_SYSTEM shadows rather than combines with user APPEND_SYSTEM",
        "Obtain separate explicit approval to apply and explicit acknowledgement of this precedence",
        "Do not merge or overwrite existing settings", "Do not copy credentials, change trust, install software",
        "registration is not readiness or permission to launch", "Do not launch agents or worktrees",
        "setup makes no ClickUp request and does not check authentication", "Do not request a token in chat",
    ),
    "factory": (
        "Follow A1–A8", "one isolated writer per worktree", "independent acceptance review in a distinct worktree",
        "approved budgets", "Keep the accepted handoff uncommitted", "Preserve target repository rules",
        "The operating developer approves launch, provider switches, scope or budget changes, external or destructive actions, and commits",
        "A ready verdict or green preflight is not launch approval", "Live Herdr orchestration and provider fallback are not implemented",
        "Do not launch agents or worktrees, switch providers, install dependencies, commit, push, publish or clean up",
        "planning and review keep their established models", "No private or global factory installation is required",
    ),
    "grilling": (
        "Inspect accessible sources before asking", "Cite the source answer instead of asking for information you can read",
        "Do not reopen settled decisions", "Ask only genuinely missing questions",
        "Ask one focused question, then wait for the answer before asking another",
        "Escalate decisions to their owner instead of guessing", "Do not interview for business, identity, voice or revenue",
        "A readiness verdict does not authorize launch", "explicitly ask to prepare or resume one selected task",
        "Show the compact revision plan", "Do not auto-run a target's explicit-only clarification skill",
    ),
}
PRIVATE_MARKERS = r"\bsamson\b|\bdarryl\b|\bgodfather\b|\bmobster\b|personal salary|/home/|/users/|~/.pi/|[a-z]:\\users\\"


class InstructionPackagingTest(unittest.TestCase):
    def resource(self, relative: str) -> str:
        resource = PACKAGE / relative
        self.assertTrue(resource.is_file(), f"missing resource: {relative}")
        return resource.read_text(encoding="utf-8")

    def test_neutral_template_and_briefs(self) -> None:
        paths = ("templates/pi/APPEND_SYSTEM.md", "factory/COORDINATOR.md", "factory/WORKER.md", "factory/REVIEWER.md")
        for path in paths:
            with self.subTest(path=path):
                text = self.resource(path)
                self.assertNotRegex(
                    text.lower(),
                    r"\bsamson\b|\bdarryl\b|\bgodfather\b|\bpersonal salary\b|\bmobster\b|"
                    r"(?m:^\s*-?\s*`?(?:scr|eli|foc|ref)`?\s*=)|/home/|/users/|~/.pi/|[a-z]:\\users\\",
                )
        pi = self.resource(paths[0])
        for clause in (
            "before proposing or editing", "one focused question at a time", "Escalate decisions to their owner",
            "A readiness verdict is not permission to launch", "developer's Pi session coordinates",
            "operating developer approves launch, provider switches, scope and budget changes",
            "external or destructive actions, settings changes and commits", "do not grant themselves permissions",
            "Do not overwrite existing settings without approval", "Say NOT VERIFIED", "Stop and escalate",
            "not an installer or evidence that Pi loaded it", "do not provide process, network or filesystem isolation",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, pi)

    def test_developer_approval_and_model_role_boundaries(self) -> None:
        coordinator = self.resource("factory/COORDINATOR.md")
        for clause in (
            "The developer's Pi session is the coordinator, not a writer",
            "The operating developer approves launch, provider switches, scope or budget changes",
            "external or destructive actions, and commits", "Keep the accepted result uncommitted",
            "Never automatically commit", "Explicit approval is required for commits",
            "Planning and acceptance review retain their established models",
            "DeepSeek fallback is for implementation workers only", "pause, preserve a resumable record",
            "wait for explicit developer approval", "No automatic fallback", "does not implement fallback execution",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, coordinator)
        self.assertNotRegex(coordinator.lower(), r"commits? (?:are |is )?automatically (?:permitted|approved)|automatically commit on")
        worker = self.resource("factory/WORKER.md")
        for clause in ("assigned writer worktree", "Do not hand off", "Do not grant yourself", "Leave changes uncommitted", "NOT VERIFIED"):
            self.assertIn(clause, worker)
        reviewer = self.resource("factory/REVIEWER.md")
        for clause in (
            "distinct from the candidate, target and writer worktrees", "never use DeepSeek", "each mutation",
            "Do not fix the candidate", "does not authenticate identity", "NOT VERIFIED",
        ):
            self.assertIn(clause, reviewer)

    def test_a14_skill_metadata_and_fixed_content(self) -> None:
        for name, clauses in SKILL_CLAUSES.items():
            with self.subTest(skill=name):
                text = self.resource(f"skills/{name}/SKILL.md")
                self.assertRegex(text, rf"\A---\nname: {name}\ndescription: '[^\n]+'\n---\n")
                self.assertIn(f"`/skill:{name}`", text)
                self.assertNotIn("disable-model-invocation", text)
                self.assertNotRegex(text.lower(), PRIVATE_MARKERS)
                for clause in clauses:
                    self.assertIn(clause, text)
                self.assertNotRegex(text.lower(), r"\b(?:start|begin|run|repeat) the seven-question")

    def test_a14_documentation_separates_platform_and_workflow_boundaries(self) -> None:
        readme = self.resource("README.md")
        manual = self.resource("docs/pi-setup.md")
        for clause in (
            "Linux SDK checks are not fresh Mac or Windows evidence",
            "Fresh macOS V9/prepared exercise, full macOS V10 and Windows follow-up are NOT VERIFIED",
            "Authenticated integrations are NOT VERIFIED", "Live Herdr orchestration and provider fallback are unsupported",
            "Registration is not overall readiness or launch approval", "indexes citations for one explicitly selected PRD",
        ):
            self.assertIn(clause, readme)
        for clause in (
            "Fresh Mac checklist (manual, NOT VERIFIED)", "with no personal Pi setup or private vault",
            "Try inspect, unapproved apply and approved apply", "Run the offline loading probe with both trust outcomes",
            "Full V10 on Mac remains NOT VERIFIED", "Record V9 as NOT VERIFIED if any required step remains unavailable",
            "Ordinary setup does not request a knowledge location", "Verify Windows separately later",
        ):
            self.assertIn(clause, manual)
        self.assertNotRegex(manual.lower(), r"\bkh\b|/home/|/users/")
        knowledge = self.resource("docs/knowledge-hub.md")
        for clause in (
            "Shared meeting notes are not established and remain deferred", "No checkout URL is needed",
            "Only for explicit knowledge configuration, supply the missing local checkout path",
            "not a full-text export", "creates only `.dcc/knowledge.json`", "Update the source checkout manually",
            "newer-looking filenames are never substituted", "not independent approval, evidence of deployment, or workflow readiness",
        ):
            self.assertIn(clause, knowledge)
        self.assertNotRegex(knowledge.lower(), PRIVATE_MARKERS)

    def test_clickup_documentation_limits_authority_and_credentials(self) -> None:
        for path, clauses in {
            "README.md": ("without checking authentication or making a request", "does not draft OpenSpec artifacts or authorize launch"),
            "docs/pi-setup.md": ("Setup makes no ClickUp request", "Setup does not perform or observe a task assessment"),
            "docs/clickup.md": ("task intake only", "Do not put a token in a command argument", "not a readiness review",
                                "fresh macOS and Windows are **NOT VERIFIED**", "not as permission to run commands"),
            "references/clickup-api.md": ("only requests are", "pass both `start`", "OAuth for apps used by others",
                                          "follows no redirects", "not a wall-clock deadline"),
        }.items():
            with self.subTest(path=path):
                text = self.resource(path)
                for clause in clauses:
                    self.assertIn(clause, text)
                if path.endswith(("/clickup.md", "/clickup-api.md")):
                    self.assertNotRegex(text.lower(), PRIVATE_MARKERS)

    def test_shipped_documentation_rejects_positive_unverified_claims(self) -> None:
        # D11/A14: no fresh Mac or Windows acceptance, and no authenticated checks.
        # D8/A14: local registration is not route readiness or live execution support.
        # Guard direct status claims, including alongside disclaimers. This is not a
        # general contradiction detector; independent review still checks other wording.
        platform = (
            r"(?:fresh mac(?:os)?(?: v9(?:/prepared exercise)?| v10| prepared exercise)?|"
            r"(?:full )?(?:macos )?v(?:9|10)(?: on (?:a )?mac(?:os)?)?|"
            r"windows(?: follow[- ]up)?|authenticated integrations?)"
        )
        workflow = r"(?:(?:complete|full|overall|end[- ]to[- ]end) (?:pi \+ herdr )?|pi \+ herdr )(?:route|workflow)"
        live = r"(?:live (?:herdr |factory )?orchestration|(?:provider|deepseek) fallback(?: execution)?)"
        status = r"(?:\s*[:=]\s*| (?:is|are|was|were|has been|have been|remains?|now) )(?:now |fully |successfully )?"
        checks = {
            "unverified acceptance": rf"\b{platform}(?:(?: and |, (?:and )?){platform})*(?:{status}(?:verified|validated|passed|complete|tested)| passed)\b",
            "complete route readiness": rf"\b{workflow}{status}(?:ready|operational|production[- ]ready)\b",
            "unsupported live capability": rf"\b{live}{status}(?:available|supported|implemented|working|operational)\b",
            "unsupported shared meetings": rf"\bshared (?:project )?meeting[- ]notes?(?: process)?{status}(?:available|working|established|configured|operational)\b",
            "mapping promoted to lookup": rf"\b(?:missing|absent|unconfigured) (?:local )?(?:knowledge |source )?mapping{status}(?:working|configured|verified|observed)\b",
            "declared status promoted to approval": rf"\b(?:draft|maintained)(?: (?:status|label))?{status}(?:approved|signed[- ]off|deployed|ready)\b",
        }
        for path in (
            "README.md", "docs/pi-setup.md", "docs/factory-handoff.md", "docs/knowledge-hub.md", "docs/scope.md", "AGENTS.md",
            "docs/clickup.md", "references/clickup-api.md",
            "factory/COORDINATOR.md", "factory/WORKER.md", "factory/REVIEWER.md",
            "references/factory-contract.md", "templates/pi/APPEND_SYSTEM.md",
            "skills/setup/SKILL.md", "skills/factory/SKILL.md", "skills/grilling/SKILL.md",
        ):
            prose = " ".join(re.sub(r"[`*_]", "", self.resource(path)).lower().split())
            for boundary, pattern in checks.items():
                with self.subTest(document=path, boundary=boundary):
                    for match in re.finditer(pattern, prose):
                        self.fail(f"A14 unsupported positive claim ({boundary}) in {path}: {match.group()}")

    def test_package_relative_role_links(self) -> None:
        expected = {
            "README.md": {"docs/factory-handoff.md", "factory/COORDINATOR.md", "factory/WORKER.md", "factory/REVIEWER.md",
                          "templates/pi/APPEND_SYSTEM.md", "docs/clickup.md", "references/clickup-api.md", "docs/task-preparation.md"},
            "factory/COORDINATOR.md": {"WORKER.md", "REVIEWER.md", "../references/factory-contract.md", "../docs/factory-handoff.md"},
            "factory/WORKER.md": {"../docs/factory-handoff.md"},
            "docs/pi-setup.md": {"factory-handoff.md", "clickup.md", "task-preparation.md"},
            "skills/grilling/SKILL.md": {"../../docs/task-preparation.md", "../../scripts/prepare.py", "../../docs/clickup.md"},
            "docs/clickup.md": {"../references/clickup-api.md", "pi-setup.md"},
            "references/clickup-api.md": {"../docs/clickup.md"},
            "docs/factory-handoff.md": {"../references/factory-contract.md"},
            "factory/REVIEWER.md": {"../references/factory-contract.md", "../docs/factory-handoff.md"},
            "skills/setup/SKILL.md": {"../../docs/pi-setup.md", "../../scripts/setup.py", "../../docs/knowledge-hub.md",
                                     "../../scripts/knowledge.py", "../../docs/clickup.md"},
            "docs/knowledge-hub.md": {"pi-setup.md"},
            "skills/factory/SKILL.md": {
                "../../factory/COORDINATOR.md", "../../factory/WORKER.md", "../../factory/REVIEWER.md",
                "../../references/factory-contract.md", "../../scripts/factory-job.py", "../../scripts/factory-alignment.py",
                "../../docs/factory-handoff.md",
            },
        }
        for relative, required in expected.items():
            with self.subTest(relative=relative):
                text = self.resource(relative)
                # The adapter guide includes inline-code examples of *source* links, not kit links.
                prose = re.sub(r"`[^`\n]*`", "", text) if relative == "docs/knowledge-hub.md" else text
                links = set(re.findall(r"\]\(([^)#]+)\)", prose))
                self.assertLessEqual(required, links, f"missing expected links: {required - links}")
                for link in links:
                    resolved = (PACKAGE / relative).parent.joinpath(link).resolve()
                    self.assertTrue(resolved.is_relative_to(PACKAGE), link)
                    self.assertTrue(resolved.is_file(), f"broken link in {relative}: {link}")


if __name__ == "__main__":
    unittest.main()
