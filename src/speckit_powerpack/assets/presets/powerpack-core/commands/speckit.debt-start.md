---
description: "Start controlled work on one or more coherent technical-debt items after a readiness gate."
---

# SpecKit Technical Debt — Start

Read `.specify/powerpack/technical-debt-policy.md`, `.specify/powerpack/technical-debt.json`, the configured backlog and every project policy in `project_policy_paths`.

This command selects existing debt for work. It does not automatically create a SPEC and does not create one SPEC per debt item.

## Readiness gate

Before any write:

1. confirm every ID exists and is unresolved;
2. reject any item that violates the effective policy floor, for example a blocker incorrectly recorded as debt or work still owned by an active review/convergence flow;
3. confirm owner, impact, deferral rationale and objective resolution criteria;
4. identify explicit dependencies and related items;
5. verify that multiple requested IDs form a coherent implementation unit;
6. if a SPEC is supplied, verify that the link is consistent and does not silently broaden that SPEC;
7. treat PR/branch/commit references only as provenance.

If a material decision, criterion or prerequisite is missing, return `NEEDS_REFINEMENT` or `BLOCKED` without writing.

## Write contract

Update only lifecycle/provenance fields of the selected items. Preserve their original text and history. Mark them `IN_PROGRESS` and append date plus SPEC/PR/branch references when supplied.

Do not move debt entries into `specs/`, delete history, reuse IDs or edit application code as a side effect.

Return the started IDs, owner, backlog path, effective project policies, work references and the resolution criteria that `speckit-debt-close` will later need to prove.
