# Developer control centre

ConnectED-first personal workspace for preparing a selected development task and coordinating its implementation through Pi + Herdr.

## Status

Documentation bootstrap only, created 18 Nov 2026. There is no runnable setup, installed skill, connector or factory implementation yet. No API keys, personal records or global harness configuration are included. No remote is configured.

The target workshop is 26 Nov 2026. macOS is the first validation target; Windows remains follow-up scope. Neither platform is verified by this bootstrap. Codex and CC Switch integration are deferred.

## Agreed workflow

Select one ClickUp task, inspect its PRD/meeting/code context, clarify gaps one question at a time, then review readiness. The developer explicitly starts the factory. Implementation and independent acceptance review preserve evidence and hand off uncommitted work.

- ClickUp is read-only.
- Shared project meeting notes in Git take priority over supplementary personal notes. Their location and contribution conventions still need confirmation.
- DeepSeek uses the connection setup Darryl already knows, with a separate team API key he will provide. Never put that key in this repository.
- DeepSeek fallback is implementation-only and requires an explicit approved switch after pausing and preserving progress. Planning and review retain their established models.
- This personal control centre lives outside target code repositories and must respect their engineering rules.

## Standalone delivery requirements

- **D27: Factory in the repo.** Ship coordinator instructions, worker/reviewer briefs, scripts, gates and dependency setup. The developer's Pi session coordinates jobs, and that developer approves actions. Neither Samson nor his vault or private global setup may be required.
- **D28: Neutral Pi setup.** Ship reproducible Pi + Herdr setup, credential-free configuration and technical operating instructions adapted from Samson's instructions. Keep scope discipline, clarification, approval boundaries and evidence-based verification. Remove Samson's identity/voice, Darryl's personal context and machine-specific assumptions. Ask before changing existing settings.

Acceptance must include a fresh macOS developer environment with no Samson vault or preconfigured personal Pi installation. Use only the repo, declared prerequisites and independently supplied credentials/access, then complete the prepared factory exercise. Check actual instruction loading and settings changes as well as workflow behaviour. These requirements are not implemented or verified yet.

## Documents

- [Agreed scope snapshot](docs/scope.md): decisions, exclusions, acceptance direction and unresolved dependencies.
- [Repository working rules](AGENTS.md): constraints for agents developing this kit.

The scope is a verbatim snapshot of `projects/ConnectED/AI Workshop/developer-control-centre-v1-scope.md` in the Samson vault, including the later 18 Nov amendments. Its wiki-links refer to that vault, not files shipped here. Source SHA-256: `e76d9d5a4234710274d929cf12083a106d3755c8102ef08cc1e9dc1a6972711c`.

## Adaptation source

During kit development, inspect and selectively adapt `../ai-os-kit`, rather than copying its working tree wholesale. This sibling repository and the Samson vault are source references, not required installations on developers' computers. Its inspected HEAD is `d4943cc630c2907c4516a6a3a92161a160b8f89e`. Git reports local changes in 44 tracked files; `git diff --ignore-space-at-eol` is empty. Preserve those files unchanged. No implementation code or license text has been copied in this bootstrap. Preserve applicable upstream licenses and attribution when adapting material.

Do not import the seven-question business onboarding, daily planning, general AI-OS audits, personal automation coaching or unrelated admin/publishing integrations.

## Next implementation boundary

Review this bootstrap and obtain explicit approval for an initial commit before a structured factory job: the factory needs a named commit baseline. Then inspect reusable components and freeze a bounded manifest with allowed paths, budgets, observable acceptance outcomes and independent review. This bootstrap does not implement or prove the scope's V1-V10 outcomes. The shipped product must carry its own factory instructions and tooling; a reference back to the private development process is not a substitute.
