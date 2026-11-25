# Offline verification profiles

Run from the repository or the extracted archive in the declared role environment. Use trusted local tools and a synthetic test home/profile; no credentials, production integrations, network dependency or existing Herdr socket are needed.

```sh
python -B scripts/verify-suite.py --check
python -B scripts/verify-suite.py                       # native (portable behaviour)
python -B scripts/verify-suite.py --profile linux-security --check
python -B scripts/verify-suite.py --profile linux-security  # supported Linux host only
```

The verifier prints selected suites and each excluded suite as NOT VERIFIED. It checks tool paths and platform capabilities before test import, validates static coverage of every shipped test declaration, and runs the selected suite once with the same Python and environment. `--check` imports and executes no test; it does not prove that tool versions, package dependencies, or tests work together. Exit 2 means invalid selection, missing prerequisite or incomplete package. Otherwise the selected child status passes through. Any reported skip is NOT VERIFIED and makes the selected suite fail. New test modules must be assigned explicitly; an existing module or class assignment covers new methods in that group. Missing, unassigned, overlapping and dynamically mismatched test IDs fail rather than being dropped.

## Native profile (macOS or Linux)

- Python 3.10+ as a non-root user for the publisher permission-denial case; Git and Node.js 22.19+ on `PATH`.
- Absolute `DCC_PI_EXECUTABLE` (Pi 1.4.0 CLI), `DCC_PI_SDK_MODULE` (matching API at `dist/index.js`, with installed dependencies), and `DCC_HERDR_EXECUTABLE` (Herdr CLI). On macOS use the runnable Node Pi CLI entrypoint from the pinned npm package (`dist/bundle/cli.js`), not a native-binary or shell-wrapper substitute. The test-only Node preload records actual entrypoint arguments before Pi changes its title, and tests match the PID to Herdr's foreground process and to the deterministic provider. Linux keeps the original Herdr process argument assertion.
- Absolute `DCC_B3_NODE` and `DCC_B3_OPENSPEC`, the Node executable and OpenSpec 1.8.0 JavaScript CLI entrypoint.

Coverage includes the portable publisher CLI checks (private immutable records, publication order, approvals/refusals), real Pi `test_native_factory_inbox.NativeInboxTest` (session opt-in, bound notifications, refusal, disable, resume and deduplication), and `test_e2e_factory_run.FactoryRunE2E` (deterministic Pi/Herdr dispatch, exact executable and arguments, busy coordinator and notifications, repair, staged-only handoff). It also includes archive/Git gates, workspace policy and other portable setup, resource, preparation and draft checks. No `unshare`, inotify, Landlock or `/proc` is used by the selected checks. Run with synthetic settings and role storage. Test fixtures use only local resources and synthetic model replies; any test transport for ClickUp is loopback-only.

## Linux security profile

The two excluded native groups are `test_e2e_factory_inbox.InboxE2E` and `test_e2e_factory.RelocatedHandoffTest`. The profile uses the absolute Linux Pi 1.4.0 CLI at `DCC_PI_EXECUTABLE` with runtime paths available under the archive fixture's Landlock rules. It checks for Linux, working `unshare -Urn`, readable `/proc` child observations, inotify and the Landlock ABI before test import. The actual tests exercise namespaces, forbidden opens/execution, no forbidden reads, bounded file handling and the original relocation/origin controls. The [handoff guide](factory-handoff.md) explains what the probes actually observe and what they do not.

A native run does not substitute for the Linux security checks. Neither profile establishes a fresh macOS V9/V10 run, Windows support, authenticated live providers, model quality or a general sandbox. Report unsupported/unrun evidence as NOT VERIFIED.
