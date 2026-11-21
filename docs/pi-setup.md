# A14 local Pi setup (S1–S3)

This slice configures a personal workspace and registers the kit's three skills. It does not configure accounts or run the complete Pi + Herdr workflow. Put the kit, workspace and Git targets in separate directories. Keep the extracted kit in place: Pi resolves absolute skill paths into it, and the skills resolve their bundled links from there. Moving the kit requires a new plan for a fresh workspace or a separate, manually managed migration of existing settings. The tool does not merge or migrate settings.

## Prerequisites and limits

- Python 3.10+ and Git, with trusted local installations and Git checkout roots. No Python runtime dependencies. Use physical paths (`pwd -P`) instead of symlinks.
- The project configuration targets Pi 1.4.0. Pi and Herdr must be supplied separately. Setup records `pi --version` and `herdr --version` if available; successful output proves only the local commands ran. No Herdr version has been validated for live operation in this slice. A missing or failing executable is reported as blocked; it does not prevent writing a valid, approved local configuration.
- The offline loading probe needs Node.js 22.19+ and the separately provisioned `@earendil-works/pi-coding-agent` SDK **1.4.0** with its dependencies, not just a native Pi executable. Neither setup nor the probe installs packages, queries registries or talks to a provider.
- The [standalone ClickUp reader](clickup.md) is read-only and available for a developer-selected task. Setup makes no ClickUp request, does not ask for credentials and does not check authentication. The [selected-task preparation CLI](task-preparation.md) is available locally. Setup does not perform or observe a task assessment. OpenSpec drafting and live factory launch remain unsupported. Live Herdr orchestration and provider fallback are unsupported. Personal Fathom is optional, not tested. The [local knowledge mapping and source index](knowledge-hub.md) are optional. Ordinary setup does not request a knowledge location; explicit knowledge configuration only needs the local checkout path if absent. Setup can observe a clean mapped checkout, not a selected-source lookup. Shared meeting notes are not established and remain deferred. A local configuration or passing probe does not make the workflow ready or authorize launch.

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

1. Record the macOS version and architecture on a fresh developer environment with no personal Pi setup or private vault. Separately approve and supply Python, Git, Pi 1.4.0, the matching SDK and Node for the probe, and the intended Herdr version. Record actual versions, not just package names.
2. Extract the shipped archive into a new stable location; make a separate disposable workspace and prepared Git target. Save before maps for HOME, the workspace and the target index. Try inspect, unapproved apply and approved apply. Compare bytes/modes and check the three new resources, saved mappings, and unchanged originals. Repeat with synthetic existing user settings and append, a conflicting project file and a saved stale plan.
3. Run the offline loading probe with both trust outcomes and inspect full evidence, including the unmerged append precedence and three relocated skill paths and expansions. Separately exercise the normal Pi CLI/TUI trust flow and `/skill:` discovery with fixture settings. Verify the effective instructions and file changes, not just the assistant's answer. Full V10 on Mac remains NOT VERIFIED until exercised.
4. When the remaining features are implemented and separately approved, exercise V9 with a prepared task, independently supplied access, ClickUp read-only context, clarification and a readiness stop. Explicitly approve a live launch, verify writer/reviewer isolation, scoped fallback separately, and the uncommitted handoff. Record V9 as NOT VERIFIED if any required step remains unavailable. Do not substitute offline registration for any of it. Verify Windows separately later.
