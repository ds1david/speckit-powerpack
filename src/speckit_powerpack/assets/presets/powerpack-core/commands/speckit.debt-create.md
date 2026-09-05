---
description: "Create a governed technical-debt item only when the work is legitimately deferrable."
---

# SpecKit Technical Debt — Create

Use this command to record deliberate technical debt. Do not use it to make an active SPEC, convergence pass or implementation review appear complete.

## Policy sources

Read, in order:

1. `.specify/powerpack/technical-debt-policy.md` — immutable PowerPack safety floor for this installation;
2. `.specify/powerpack/technical-debt.json` — storage format, backlog path, template path, prefix and project-policy references;
3. every existing project policy listed in `project_policy_paths`.

The effective policy is cumulative. Project policy may be stricter or add domain-specific ownership/fields, but MUST NOT weaken the PowerPack floor. If policies conflict, apply the stricter rule and report the conflict.

## Mandatory creation gate

Before writing anything, prove all conditions below:

- the work is not required by the active SPEC, acceptance criteria, constitution or mandatory gate;
- it is not an unresolved `speckit-implement-review` finding;
- it is not an actionable `speckit-converge` gap;
- it is not a P0/BLOCKER or immediate correctness/security/compliance/data-integrity blocker;
- the problem has concrete evidence and impact;
- deferral has an explicit rationale;
- an objective resolution criterion exists;
- owner is known;
- the backlog was searched for duplicates and related items.

If any mandatory condition fails, return `NOT_DEBT` with the current flow that must own the work. Do not create a backlog item.

## Grouping and deduplication

Prefer one coherent capability over multiple near-duplicate debt entries. Never create one SPEC per debt by default. If the proposed item materially overlaps an existing item, recommend linking/expanding that item instead of minting a new ID.

## Write contract

Resolve `storage_format`, `backlog_path`, `template_path` and `id_prefix` from `.specify/powerpack/technical-debt.json`.

If the configured backlog does not exist and `storage_format` is `markdown-v1`, create it by copying the configured `template_path` verbatim, then append the new item. Do not invent a second markdown shape when the canonical template is available.

If a project uses another storage format, follow the stricter project policy/adapter contract; if no deterministic write contract exists, return `BLOCKED_CONFIGURATION` rather than guessing.

Allocate the next stable sequential ID for the configured prefix. Never reuse or renumber IDs.

Record at least ID/title, owner, description, origin/provenance, impact, priority, status `OPEN`, readiness, objective resolution criteria, deferral rationale, dependencies/blockers, probable future SPEC/capability when known, creation date/evidence and lifecycle history.

Do not modify code, SPECs, PRs or unrelated debt items.

## Result

Return `CREATED`, `DUPLICATE`, `GROUP_WITH_EXISTING`, `NOT_DEBT`, `BLOCKED`, `BLOCKED_CONFIGURATION` or `NEEDS_REFINEMENT`, with evidence for the decision.
