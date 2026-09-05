# Technical Debt Governance

PowerPack treats technical debt as a deliberate, auditable deferral of **non-blocking** engineering work. It is never an escape hatch for code review, convergence, correctness, security, data-integrity or acceptance-criteria failures.

## Policy precedence

The PowerPack policy is the minimum safety floor. Projects may declare stricter rules through `.specify/powerpack/technical-debt.json -> project_policy_paths`, but a project policy cannot weaken these invariants.

When a project has an existing debt-governance document, the debt skills read it before acting and combine it with this baseline. Project-specific owners, prefixes, domains and extra required fields remain local to the project.

## Creation gate

A new debt item may be created only when all of the following are true:

1. the work is not required to satisfy the active SPEC, acceptance criteria, constitution or mandatory quality gate;
2. it is not an unresolved finding from an active `speckit-implement-review` round;
3. it is not an actionable gap emitted by active `speckit-converge`;
4. it is not a P0/BLOCKER or an immediate correctness/security/compliance/data-integrity release blocker;
5. evidence shows the problem exists and its impact is understood;
6. there is a concrete reason to defer it now;
7. there is an objective resolution criterion;
8. ownership is explicit;
9. duplicates and closely related items have been checked first.

If any of items 1–4 fail, the work belongs to the current delivery flow and MUST be fixed there instead of becoming debt.

## Required fields

Every item records at least:

- stable ID;
- owner;
- description;
- origin/provenance;
- impact;
- priority (`P1`, `P2` or `P3` by default);
- status;
- readiness;
- objective resolution criteria;
- deferral rationale;
- dependencies/blockers when known;
- probable future SPEC/capability when known;
- lifecycle history and evidence.

`P0` is intentionally absent from the default backlog priorities: a blocker is handled in the flow that discovered it.

## Lifecycle

```text
OPEN -> IN_PROGRESS -> RESOLVED
```

Readiness is independent from status:

```text
READY | BLOCKED | NEEDS_REFINEMENT | RESOLVED
```

Starting debt does not automatically create a SPEC. Multiple related items should be grouped into a coherent capability when that produces a better implementation unit.

IDs are stable, never reused or renumbered. Historical description and provenance are preserved across lifecycle updates.

## Closing policy

`RESOLVED` requires objective evidence against the original resolution criteria. A PR number, commit SHA or agent statement alone is provenance, not proof.

When code validation is required, use the PowerPack capability-selected quality gate rather than a language/framework-specific command embedded in the debt skill. Residual work prevents full closure; do not hide residuals by declaring the parent item resolved.

## Default storage

The default backlog is `docs/technical-debt.md`. Projects may change this in `.specify/powerpack/technical-debt.json`.

The debt skills are:

- `speckit-debt-create`
- `speckit-debt-list`
- `speckit-debt-consult`
- `speckit-debt-start`
- `speckit-debt-close`
