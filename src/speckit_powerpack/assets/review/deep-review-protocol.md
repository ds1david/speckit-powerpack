# PowerPack Deep Review Evidence Protocol

## Purpose

Determine, with reproducible evidence, whether the current implementation snapshot satisfies the active SPEC without introducing regressions outside the requested scope. A review is a technical quality gate, not a style pass and not a source of optional backlog suggestions.

Every review round is bound to one immutable snapshot identity: SPEC, base SHA, merge-base, head SHA and a snapshot digest. Previous approvals, green CI, PR descriptions and implementer claims are hypotheses, never proof.

## Required evidence order

Read, when present, in this order:

1. the round context and snapshot identity;
2. project instructions and constitution/policies;
3. the active SPEC artifacts (`spec.md`, `plan.md`, `tasks.md`, `research.md`, `data-model.md`, `quickstart.md`, `contracts/`, `checklists/`);
4. the complete diff against the merge-base and the complete contents of every changed file;
5. callers, callees, implementations, schemas, migrations, configuration and tests necessary to establish blast radius;
6. the previous round only to verify prior findings, never to inherit its conclusion.

All changed files MUST appear in both `coverage.changed_files` and `coverage.inspected_files`. Related files actually read belong in `inspected_files` too.

## Mandatory review fronts

The reviewer must cover all fronts and attach concise evidence to each:

1. `SPEC_COMPLIANCE` — requirements, acceptance scenarios, success criteria and tasks map to implementation and tests/proof.
2. `BEHAVIORAL_REGRESSION` — compare baseline and head across happy path, validation, errors, replay/retry, restart, shutdown and side effects where applicable.
3. `ARCHITECTURE_AND_CONTRACTS` — boundaries, dependency direction, public contracts, schemas, migrations, serialization and compatibility.
4. `STATE_CONCURRENCY_AND_FAILURES` — ownership, transitions, TOCTOU, races, idempotency, retries, ordering, partial failure, rollback and resource cleanup.
5. `PERSISTENCE_DETERMINISM_IDEMPOTENCY` — transaction boundaries, constraints, read/write consistency, stable ordering, time/random/UUID effects, replay and restart determinism where applicable.
6. `TESTS_AND_COMPOSITION_ROOT` — tests can fail for the defect they claim to cover, negative/concurrent cases are represented, mocks do not hide behavior and the feature is reachable in the real composition root.
7. `DOCUMENTATION_AND_OPERABILITY` — diagnostics, logs, metrics, runbooks, documentation, performance and operational behavior affected by the change.
8. `SECURITY_AND_SCOPE` — authentication/authorization, secret handling, validation, injection/deserialization/path traversal risks and unrelated scope creep.

`NOT_APPLICABLE` is allowed only with concrete evidence explaining why the front does not apply.

## Procedure for every round

### Pass 1 — previous findings

On round 2+, validate every finding from the immediately previous review against the current head. Report each prior ID exactly once as one of:

- `RESOLVED`
- `PARTIALLY_RESOLVED`
- `NOT_RESOLVED`
- `REGRESSED`

Do not silently drop or rename previous IDs. A repeated material defect after it was claimed resolved is a repeated-finding condition and must be surfaced explicitly to the PowerPack loop.

### Pass 2 — full snapshot review

Discard the previous verdict and review the entire current snapshot again against the merge-base. Do not review only the correction delta.

For every relevant production flow, inspect when applicable:

`input -> validation -> decision -> persistence/effect -> observability -> failure/recovery`

For concurrent state, identify ownership, valid transitions and the synchronization/linearization point.

### Pass 3 — adversarial verdict challenge

Before returning the verdict, try to invalidate it. Look for the strongest remaining counterexample in concurrency, replay, restart, partial failure, boundaries, constraints, side effects, shutdown, composition root, security and vacuously green tests.

For `CHANGES_REQUIRED`, ensure each finding describes a concrete failure, observable impact and verifiable acceptance criteria rather than personal preference.

## Finding discipline

Every concrete defect is a finding regardless of severity. Findings are work for the current implementation-review loop and MUST NOT be converted to technical debt, backlog, TODO or future issue to obtain convergence.

A finding must include:

- `id`
- `severity`
- `category`
- `title`
- `file`
- `line`
- `evidence`
- `failure_scenario`
- `behavioral_impact`
- `required_change`
- `acceptance_criteria`

If context, tooling or infrastructure limitations prevent a responsible conclusion, use `BLOCKED`; do not approve by absence of evidence.

## Output contract

Return one JSON object using schema `2.0` with `review_context`, `coverage`, all mandatory fronts and `findings`.

Allowed requirement statuses: `PASS`, `PARTIAL`, `FAIL`, `NOT_APPLICABLE`.
Allowed baseline results: `PRESERVED`, `CHANGED_AS_SPECIFIED`, `REGRESSION`, `NOT_APPLICABLE`.
Allowed front statuses: `PASS`, `FINDINGS`, `BLOCKED`, `NOT_APPLICABLE`.

`APPROVED` requires `findings: []`, all changed files inspected, no requirement in `PARTIAL/FAIL`, no baseline `REGRESSION`, every previous finding `RESOLVED`, and all fronts `PASS/NOT_APPLICABLE`.

The PowerPack validator is authoritative for structural validation:

```bash
python .specify/powerpack/bin/review_protocol.py validate --input <review.json>
python .specify/powerpack/bin/review_protocol.py validate --input <review.json> --previous <previous-review.json>
```
