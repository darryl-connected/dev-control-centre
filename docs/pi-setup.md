# Set up DCC with Pi

This slice configures a personal workspace and registers the kit's three skills. It does not configure accounts, authenticate a provider or complete the prepared macOS exercise. The separately invoked factory loop ships in this repository; setup does not run it. Put the kit, workspace and Git targets in separate directories. Keep the extracted kit in place: Pi resolves absolute skill paths into it, and the skills resolve their bundled links from there. Moving the kit requires a new plan for a fresh workspace or a separate, manually managed migration of existing settings. The tool does not merge or migrate settings.

## Quickstart (macOS)

### 1. Install Pi and sign in

If you don’t already have Pi, get the latest stable release using the official installer from <https://pi.dev/>. Run this in macOS Terminal:

```sh
curl -fsSL https://pi.dev/install.sh | sh
```

Follow the installer’s instructions if you need to reopen Terminal. From the root of your existing DCC Git checkout, run:

```sh
pi --version
pi
```

Inside Pi, type `/login`, choose the provider for your supported subscription, and complete sign-in there. Don’t paste keys or verification codes into the chat. If needed, use `/model` to select a model available through your account.

**Version note:** DCC’s automated checks use Pi 1.4.0. First-run setup with the latest Pi on a fresh Mac is **NOT VERIFIED**. A working Pi login lets you use the starter prompt; it does not verify the factory’s model routes.

### 2. Paste this into Pi in the DCC checkout

```text
I’m in the DCC checkout. Help me set up DCC using this checkout’s AGENTS.md and docs/pi-setup.md. Don’t assume /skill:setup is available yet.

Check Git and Python 3.10+. Ask only for the path to a separate, existing DCC workspace and the name and path of my local app Git checkout if you can’t determine them. If a directory or prerequisite is missing, tell me what I need to supply; don’t create directories or install software. Run scripts/setup.py inspect as documented, saving its JSON plan outside the workspace and the Git checkouts. Show me the exact files it would create, any blockers, and how the workspace’s APPEND_SYSTEM.md takes precedence over my user copy. Stop until I approve the plan and separately acknowledge that precedence.

After both confirmations, apply that exact plan using the documented flags. Tell me how to open Pi in the new workspace, review its trust prompt, and check that the DCC skills are listed. Don’t edit global Pi settings, change either checkout, ask for secrets, install Herdr, or start a factory job.
```

### 3. Open Pi in your new workspace

After setup applies the plan, exit Pi in the kit checkout. In Terminal, change to the **separate DCC workspace** and run `pi` again. Review the workspace’s `.pi/` files before granting trust at Pi’s prompt. Once trusted, Pi uses the workspace’s `.pi/APPEND_SYSTEM.md` and registers the DCC skills. Use Pi’s slash-command suggestions to look for `/skill:setup`, `/skill:grilling`, and `/skill:factory`; you don’t need to run them to check discovery.

Herdr isn’t needed for these steps. Install and verify it separately before trying the factory. Skill discovery is not proof that ClickUp, the factory model routes, or an end-to-end factory run work.

## Prerequisites and limits

- Python 3.10+ and Git, with trusted local installations and Git checkout roots. No Python runtime dependencies. Use physical paths (`pwd -P`) instead of symlinks.
- The project configuration targets Pi 1.4.0 and Herdr 0.9.1, supplied separately. Setup records `pi --version` and `herdr --version` if available; successful output proves only the local commands ran. The loop's Linux QA exercises real Pi 1.4.0 and Herdr 0.9.1 with deterministic synthetic providers; it does not establish authenticated live operation or fresh macOS readiness. A missing or failing executable is reported as blocked; it does not prevent writing a valid, approved local configuration.
- The offline loading probe needs Node.js 22.19+ and the separately provisioned `@earendil-works/pi-coding-agent` SDK **1.4.0** with its dependencies, not just a native Pi executable. Neither setup nor the probe installs packages, queries registries or talks to a provider.
- The [standalone ClickUp reader](clickup.md) is read-only and available for a developer-selected task. Setup makes no ClickUp request, does not ask for credentials and does not check authentication. The [selected-task preparation CLI](task-preparation.md) is available locally. Setup does not perform or observe a task assessment. The [OpenSpec draft helper](task-preparation.md#draft-and-validate-one-new-change) is separate and requires a trusted local OpenSpec 1.8.0 CLI, a current saved scope and explicit approval of the draft. Setup does not inspect that CLI or the target's OpenSpec workflow. The loop requires explicit developer launch approval and fixed inbox records. Live provider/account operation through it and automatic fallback are NOT VERIFIED. Personal Fathom is optional, not tested. The [local knowledge mapping and source index](knowledge-hub.md) are optional. Ordinary setup does not request a knowledge location; explicit knowledge configuration only needs the local checkout path if absent. Setup can observe a clean mapped checkout, not a selected-source lookup. Shared meeting notes are not established and remain deferred. A local configuration or passing probe does not make the workflow ready or authorize launch.

## Inspect, approve and apply

From the kit root, use an existing personal workspace directory and at least one named local Git target. Repeat `--repo` for additional targets. Store the plan outside the workspace and repositories; it contains local paths and hashes, not credentials. Review the plan before applying.

```sh
python3 -B scripts/setup.py inspect --workspace "$WORKSPACE" \
  --repo "app=$TARGET_REPO" > "$PLAN_OUTSIDE_WORKSPACE"
```

Inspection prints only. Its `readiness` object reports successful local commands and blocked features separately. It does not launch an interactive Pi or Herdr session. A missing mapping or an invalid destination must be corrected and inspected again. The kit checks known on-disk Pi skill discovery locations for collisions. It refuses ambiguous skill metadata, custom user skill/package/extension settings and discovered extensions it cannot audit without running them. It never evaluates such extensions. Use a fresh fixture or consult the operating developer about conflicting configuration; do not remove or change someone else's settings to get through setup.

**A trusted project `APPEND_SYSTEM.md` shadows rather than combines with user `APPEND_SYSTEM.md`.** The user's file stays byte-identical, but its content is absent from a trusted session's effective prompt. Inspect refuses conflicting project settings or append bytes (including malformed files or symlinks); the presence of other context files does not imply a neutral full prompt. Approve the exact plan and separately acknowledge this precedence before applying:

```sh
python3 -B scripts/setup.py apply --plan "$PLAN_OUTSIDE_WORKSPACE" \
  --approve --acknowledge-instruction-shadow
```

Apply rechecks the plan's paths, file identities/content and conflicts before creating anything. It creates only `.pi/settings.json`, `.pi/APPEND_SYSTEM.md`, `.dcc/workspace.json`, and any missing `.pi` and `.dcc` directories. It never copies auth, writes `trust.json`, merges settings or touches targets. An already-applied plan is stale; inspect again (omit `--repo` to use the saved mappings) to see `unchanged`. This is preflight plus exclusive creation, not a multi-file transaction or protection from concurrent directory changes, storage failures or processes with the same permissions. Run in a trusted workspace without concurrent edits.

## Offline loading evidence

Use a disposable physical directory with child directories `home` and `workspace`, outside the kit. Set `HOME` to that `home`, unset `PI_CODING_AGENT_DIR`, and use an environment without production credentials. Run inspect and approved apply there using a disposable Git target outside the workspace. Optionally place a synthetic `APPEND_SYSTEM.md` in the fixture's `home/.pi/agent` to check shadowing. Do not point the probe at a real user profile. With `DCC_PI_SDK_MODULE` set to the SDK's absolute `dist/index.js`:

```sh
HOME="$FIXTURE_ROOT/home" node scripts/verify-pi-resources.mjs --fixture-root "$FIXTURE_ROOT"
```

The probe runs the real Pi loader with trust granted and denied in memory; it does not save trust. It records the effective prompts, resource paths, hashes, diagnostics and actual `/skill:setup`, `/skill:factory` and `/skill:grilling` command expansions with caller arguments. A local Pi faux provider records the pre-model context and returns a synthetic response without calling tools or a live model. Missing dependencies or bad resource linkage are failures, not skips. The supplied instructions do not sandbox future tool use. This probe is not CLI/TUI parity, a credential check or a conversation test.

## Optional local handoff notices

[Factory handoff](factory-handoff.md) is separate from setup registration. It uses an explicit per-process `pi -e` and per-conversation opt-in for a developer-approved job; setup does not install or enable it. The inbox only notifies. Linux offline TUI evidence for that adapter does not complete the prepared Mac exercise.

## Fresh Mac checklist (manual, NOT VERIFIED)

Before recommending the latest release to developers, rehearse the quickstart verbatim from a Git checkout on a fresh Mac. Record the installed Pi version and verify that the starter prompt stops at the review gate, the approved plan applies, and a fresh trusted workspace session actually loads the DCC instructions and all three skills. This quickstart rehearsal does not need Herdr; keep the pinned checks and full prepared exercise below separate.

1. Record the macOS version and architecture on a fresh developer environment with no personal Pi setup or private vault. Separately approve and supply Python, Git, Pi 1.4.0, the matching SDK and Node for the probe, and the intended Herdr version. Record actual versions, not just package names.
2. Extract the shipped archive into a new stable location; make a separate disposable workspace and prepared Git target. Save before maps for HOME, the workspace and the target index. Try inspect, unapproved apply and approved apply. Compare bytes/modes and check the three new resources, saved mappings, and unchanged originals. Repeat with synthetic existing user settings and append, a conflicting project file and a saved stale plan.
3. Run the offline loading probe with both trust outcomes and inspect full evidence, including the unmerged append precedence and three relocated skill paths and expansions. Separately exercise the normal Pi CLI/TUI trust flow and `/skill:` discovery with fixture settings. Verify the effective instructions and file changes, not just the assistant's answer. Full V10 on Mac remains NOT VERIFIED until exercised.
4. When the remaining features are implemented and separately approved, exercise V9 with a prepared task, independently supplied access, ClickUp read-only context, clarification and a readiness stop. Where the target uses OpenSpec, separately approve an exact draft, observe strict validation and review the written artifacts. Explicitly approve one live launch separately, verify the effective writer/reviewer/coordinator routes, exercise one approved in-scope repair and the uncommitted exact handoff. Record V9 as NOT VERIFIED if any required step remains unavailable. Do not substitute offline registration or deterministic-provider loop tests for any of it. Verify Windows separately later.
