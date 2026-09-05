---
description: "Create a governed technical-debt item only when the work is legitimately deferrable."
---

# SpecKit Technical Debt — Create

Use this command to record deliberate technical debt. Do not use it to make an active SPEC, convergence pass or implementation review appear complete.

## Policy sources

1. Read `docs/TECHNICAL_DEBT.md` from the installed PowerPack documentation when available, or the project-local copy/reference configured by PowerPack.
2. Read `.specify/powerpack/technical-debt.json`.
3. Read every existing project policy listed in `project_policy_paths`.

The PowerPack policy is the minimum floor. Project policy may be stricter but MUST NOT weaken it.

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

Resolve `backlog_path` and `id_prefix` from `.specify/powerpack/technical-debt.json`. If the backlog does not exist, create a minimal governed backlog with the PowerPack marker and no project-specific assumptions.

Allocate the next stable sequential ID for the configured prefix. Never reuse or renumber IDs.

Record at least ID/title, owner, description, origin/provenance, impact, priority, status `OPEN`, readiness, objective resolution criteria, deferral rationale, dependencies/blockers, probable future SPEC/capability when known, creation date/evidence and lifecycle history.

Do not modify code, SPECs, PRs or unrelated debt items.

## Result

Return `CREATED`, `DUPLICATE`, `GROUP_WITH_EXISTING`, `NOT_DEBT`, `BLOCKED` or `NEEDS_REFINEMENT`, with evidence for the decision.
