# PowerPack Technical Debt Policy

Technical debt is a deliberate, auditable deferral of non-blocking engineering work. It is never an escape hatch for an active SPEC, convergence gap, code-review finding, failed mandatory gate, P0/BLOCKER, correctness/security/compliance/data-integrity failure or acceptance-criteria obligation.

## Precedence

This policy is the minimum safety floor. Project-local policies listed in `.specify/powerpack/technical-debt.json -> project_policy_paths` may add owners, domains, prefixes, fields, stricter readiness rules and stricter closure evidence. They MUST NOT make the PowerPack floor more permissive.

## Creation gate

A new debt item may be created only when:

1. it is not required by the active SPEC, acceptance criteria, constitution or mandatory delivery gate;
2. it is not an unresolved `speckit-implement-review` finding;
3. it is not an actionable `speckit-converge` gap;
4. it is not P0/BLOCKER or an immediate correctness/security/compliance/data-integrity blocker;
5. the problem and impact have objective evidence;
6. deferral now has an explicit rationale;
7. an objective resolution criterion exists;
8. ownership is explicit;
9. duplicates/related capabilities were checked first.

If conditions 1–4 fail, return the work to the current delivery flow. Do not create debt.

## Required fields

Every new item records stable ID, owner, description, origin/provenance, impact, priority, status, readiness, objective resolution criteria, deferral rationale, dependencies/blockers when known, probable future SPEC/capability when known, lifecycle history and evidence.

Default backlog priorities are P1/P2/P3. P0 is intentionally not a backlog priority.

## Lifecycle

`OPEN -> IN_PROGRESS -> RESOLVED`

Readiness is independent: `READY | BLOCKED | NEEDS_REFINEMENT | RESOLVED`.

Starting debt does not automatically create a SPEC. Prefer coherent capability groups over one SPEC per debt item. IDs are stable and never reused or renumbered. Historical text/provenance is preserved.

## Closure

`RESOLVED` requires objective evidence against the original resolution criteria. PR/commit/branch references are provenance, not proof. When executable validation is necessary, use the PowerPack capability-selected gate. Relevant residual work prevents full closure.
