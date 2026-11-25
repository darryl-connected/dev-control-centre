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
        "Obtain explicit approval to apply, plus acknowledgement of this precedence only before creating the opt-in template",
        "Do not merge or overwrite existing settings", "Do not copy credentials, change trust, install software",
        "registration is not readiness or permission to launch", "Do not launch agents or worktrees",
        "setup makes no ClickUp request and does not check authentication", "Do not request a token in chat",
    ),
    "factory": (
        "Follow A1–A8", "one isolated writer per worktree", "independent acceptance review in a distinct worktree",
        "approved budgets", "Keep the accepted handoff uncommitted", "Preserve target repository rules",
        "The operating developer approves launch, provider switches, scope or budget changes, external or destructive actions, and commits",
        "A ready verdict or green preflight is not launch approval", "The coordinator-invoked loop is available locally",
        "Do not launch agents or worktrees, switch providers, install dependencies, commit, push, publish or clean up",
        "planning and review keep their approved models for the active job", "No private or global factory installation is required",
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

    def test_shipped_reviewer_instructions_defer_to_configured_job_route(self) -> None:
        # Read the coordinator, customization guide and reviewer brief together. This
        # checks the shipped prose contract, not Pi loading or model behavior.
        coordinator = self.resource("factory/COORDINATOR.md")
        policy = self.resource("docs/customization.md")
        reviewer = self.resource("factory/REVIEWER.md")
        self.assertIn("The shipped defaults are", coordinator)
        self.assertIn("select other exact routes and reasoning for a new job", coordinator)
        self.assertIn("A writer and reviewer may use the same model in separate sessions and worktrees", policy)
        self.assertNotRegex(
            reviewer.lower(),
            r"\b(?:openai/gpt-6\.1-sol|deepseek/deepseek-flash|never use deepseek|acceptance uses)\b",
            "role instructions must not turn a default or brand into an acceptance requirement",
        )
        self.assertIn("Use the exact reviewer provider, model and reasoning frozen in the approved job", reviewer)
        self.assertIn("A model can be shared across roles; the acceptance session and worktree must be independent", reviewer)
        self.assertIn("does not change target repository rules or grant external access", reviewer)

    def test_review_context_and_model_recommendations_do_not_block_launch(self) -> None:
        coordinator = self.resource('factory/COORDINATOR.md')
        self.assertIn('advisory, not launch requirements', coordinator)
        self.assertIn('A smaller or unknown capacity alone is not a reason to refuse', coordinator)
        self.assertIn('effective backend capacity as NOT VERIFIED', coordinator)
        self.assertIn('separate session and worktree and an exact-candidate receipt', coordinator)
        policy = self.resource('docs/customization.md')
        self.assertIn('"reviewer": {"provider": "local-lab", "model": "Builder"', policy)
        self.assertIn('Do not use this edit to change roles or reset spending for an already approved job', policy)
        for path in ('README.md', 'docs/customization.md', 'docs/pi-setup.md', 'docs/scope.md', 'factory/COORDINATOR.md',
                     'factory/WORKER.md', 'factory/REVIEWER.md', 'templates/pi/APPEND_SYSTEM.md',
                     'skills/factory/SKILL.md', 'references/factory-contract.md'):
            prose = ' '.join(self.resource(path).lower().split())
            with self.subTest(path=path):
                self.assertNotRegex(prose, r'(?:require an independent reviewer with|reviewer must have|'
                                    r'verify the exact reviewer route has) [^.]{0,100}(?:1m|1,000,000)')
                self.assertNotRegex(prose, r'(?:writer and reviewer must use different models|'
                                    r'refuse launch if [^.]*context is unknown|block launch if [^.]*capacity is unknown)')

    def test_coordinator_does_not_claim_auto_commit_authority(self) -> None:
        coordinator = self.resource("factory/COORDINATOR.md")
        self.assertNotRegex(coordinator.lower(), r"commits? (?:are |is )?automatically (?:permitted|approved)|automatically commit on")

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

    def test_shipped_preview_recipe_uses_optional_overall_semantics(self) -> None:
        coordinator = self.resource("factory/COORDINATOR.md")
        self.assertIn("--overall-limit CALLS:MINUTES", coordinator)
        self.assertNotIn("--shared-limit", coordinator)
        self.assertIn("No aggregate ceiling is implied", coordinator)

    def test_a14_documentation_separates_platform_and_workflow_boundaries(self) -> None:
        readme = self.resource("README.md")
        manual = self.resource("docs/pi-setup.md")
        for clause in (
            "Linux SDK checks are not fresh Mac or Windows evidence",
            "Fresh macOS V9/prepared exercise, full macOS V10 and Windows follow-up are NOT VERIFIED",
            "Authenticated integrations are NOT VERIFIED", "The coordinator-invoked loop is available locally",
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
            "README.md": ("without checking authentication or making a request", "Preparation does not draft OpenSpec artifacts or authorize launch"),
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
            "README.md", "docs/pi-setup.md", "docs/customization.md", "docs/factory-handoff.md", "docs/knowledge-hub.md", "docs/scope.md", "AGENTS.md",
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
                          "templates/pi/APPEND_SYSTEM.md", "docs/clickup.md", "references/clickup-api.md", "docs/task-preparation.md", "docs/customization.md"},
            "docs/customization.md": {"pi-setup.md", "../templates/dcc/policy.json"},
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
