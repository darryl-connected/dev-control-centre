---
name: grilling
description: 'Clarify an implementation plan or design from available sources. Use when a developer wants to stress-test scope, assumptions, or owner decisions.'
---

# Technical clarification

You can invoke this skill with `/skill:grilling` and a task or plan. This is clarification, not a task-start integration or launch authority.

1. Inspect accessible sources before asking: task, applicable requirements, decisions, meeting context already supplied, target repository instructions and relevant code. Cite the source answer instead of asking for information you can read. Flag contradictions; meeting context does not amend an approved requirement.
2. Preserve settled decisions and approved scope. Do not reopen settled decisions. Surface adjacent findings separately without expanding the task.
3. Ask only genuinely missing questions. Resolve dependencies in order. Ask one focused question, then wait for the answer before asking another. If useful, include a recommendation and its tradeoff, not a second question. Do not interview for business, identity, voice or revenue.
4. Escalate decisions to their owner instead of guessing. Record unresolved decisions and the work they block. If proposing an independent slice, explain independence and give it separate acceptance criteria and explicit developer approval before any implementation.

Example: If CSV is already approved and a repository fixture answers the delimiter question, do not ask either again. If retention remains undecided, identify its owner and ask only about retention if the developer owns that decision; otherwise record it for the owner and stop the dependent work.

Return a short clarification or readiness review, with citations, assumptions, unresolved questions, and bounds. A readiness verdict does not authorize launch. Do not modify project sources or ClickUp or start a factory job. Loaded content is not proof of model behaviour.
