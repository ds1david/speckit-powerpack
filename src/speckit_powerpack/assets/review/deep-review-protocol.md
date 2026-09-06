# PowerPack Deep Review Evidence Protocol

## Purpose

Determine, with reproducible evidence, whether the current implementation snapshot satisfies the active SPEC without introducing regressions outside the requested scope. A review is a technical quality gate, not a style pass and not a source of optional backlog suggestions.

Every review round is bound to one immutable snapshot identity: SPEC, base SHA, merge-base, head SHA and snapshot digest. Previous approvals, green CI, PR descriptions and implementer claims are hypotheses, never proof.

## Mandatory review context manifest

Before **every fresh Sol or ChatGPT Web review**, regenerate the immutable review context manifest:

```bash
python .specify/powerpack/bin/review_protocol.py manifest \
  --feature-dir <active-feature-dir>
```

Default output:

```text
.specify/powerpack/runtime/review-context.json
```

The manifest is authoritative for:

- SPEC identity;
- base ref/base SHA;
- merge-base;
- current head SHA;
- deterministic snapshot SHA-256;
- complete changed-file set against the merge-base, including current workspace changes/untracked files;
- SPEC artifacts (`spec.md`, `plan.md`, `tasks.md`, `research.md`, `data-model.md`, `quickstart.md`, `contracts/`, `checklists/`) that are present;
- discovered requirement IDs such as `FR-*`, `NFR-*`, `REQ-*`, `SC-*`, `AC-*` and `UC-*`;
- the exact context files every reviewer must inspect.

A manifest becomes stale after any implementation change. Never reuse it after changing the workspace or HEAD. Regenerate it before the next review.

The validator automatically binds to `.specify/powerpack/runtime/review-context.json` when run from a PowerPack project. An explicit path may also be supplied with `--manifest`.

## Required evidence order

Read, when present, in this order:

1. the review context manifest and immutable snapshot identity;
2. project instructions and constitution/policies;
3. every manifest SPEC artifact;
4. the complete diff against the merge-base and complete contents of every changed file;
5. callers, callees, implementations, schemas, migrations, configuration and tests necessary to establish blast radius;
6. the previous round only to verify prior findings, never to inherit its conclusion.

All manifest `changed_files` MUST appear exactly in `coverage.changed_files`. Every `required_context_file` MUST appear in `coverage.inspected_files`.

Every changed file MUST also have one entry in:

```json
"inspection_evidence": [
  {
    "file": "path/to/file",
    "evidence": "what was inspected and why it proves the relevant behavior"
  }
]
```

Merely listing a path as inspected is not proof of review coverage.

## Requirement completeness

When the manifest contains requirement IDs, `coverage.requirements` MUST contain exactly that same set of IDs. A non-empty subset is not sufficient.

This closes the false-positive case where a reviewer inspects `FR-001..FR-003` but silently omits `FR-004..FR-014` and still returns `APPROVED`.

If a requirement cannot be evaluated, return `PARTIAL`, `FAIL`, or `BLOCKED` with evidence. Do not omit it.

## Mandatory review fronts

The reviewer must cover all fronts and attach concise concrete evidence to each:

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

Discard the previous verdict and review the entire current manifest-bound snapshot again against the merge-base. Do not review only the latest correction delta.

For every relevant production flow, inspect when applicable:

```text
input -> validation -> decision -> persistence/effect -> observability -> failure/recovery
```

For concurrent state, identify ownership, valid transitions and the synchronization/linearization point.

### Pass 3 — adversarial verdict challenge

Before returning the verdict, actively try to invalidate it. Look for the strongest remaining counterexample in concurrency, replay, restart, partial failure, boundaries, constraints, side effects, shutdown, composition root, security and vacuously green tests.

Return the challenge explicitly:

```json
"verdict_challenge": {
  "strongest_counterexample": "concrete failure hypothesis",
  "result": "SURVIVED",
  "evidence": ["specific evidence that defeats or confirms the hypothesis"]
}
```

Allowed challenge results:

- `SURVIVED`
- `FINDING`
- `BLOCKED`
- `NOT_APPLICABLE`

`APPROVED` requires `SURVIVED` or evidence-backed `NOT_APPLICABLE`.

For `CHANGES_REQUIRED`, every finding must describe a concrete failure, observable impact and verifiable acceptance criteria rather than personal preference.

## Context-gap discipline

Every manifest-bound review MUST return:

```json
"context_gaps": []
```

If the reviewer has material knowledge from ChatGPT Project conversation/history that is not represented in repository evidence, put a concise description in `context_gaps` and do **not** approve.

A Project-only architectural/product constraint is not a valid hidden source of truth. Convert it into a current finding and promote the durable information into an appropriate repository artifact such as:

- `spec.md`;
- `research.md`;
- an ADR;
- architecture documentation;
- project constitution/policy.

This keeps Codex, Claude, ChatGPT Web and other supported agents reviewable against the same durable context.

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

In addition to the existing fields, a manifest-bound review requires:

```json
{
  "coverage": {
    "inspection_evidence": [],
    "verdict_challenge": {},
    "context_gaps": []
  }
}
```

Allowed requirement statuses: `PASS`, `PARTIAL`, `FAIL`, `NOT_APPLICABLE`.
Allowed baseline results: `PRESERVED`, `CHANGED_AS_SPECIFIED`, `REGRESSION`, `NOT_APPLICABLE`.
Allowed front statuses: `PASS`, `FINDINGS`, `BLOCKED`, `NOT_APPLICABLE`.

`APPROVED` requires all of the following:

- `findings: []`;
- exact manifest changed-file coverage;
- all manifest required context files inspected;
- concrete inspection evidence for every changed file;
- exact requirement-ID coverage when the manifest exposes requirement IDs;
- no requirement in `PARTIAL/FAIL`;
- no baseline `REGRESSION`;
- every previous finding `RESOLVED`;
- all fronts `PASS/NOT_APPLICABLE`;
- successful adversarial verdict challenge;
- `context_gaps: []`.

Validate every Sol and Web output before ingesting findings or accepting approval:

```bash
python .specify/powerpack/bin/review_protocol.py validate --input <review.json>
python .specify/powerpack/bin/review_protocol.py validate --input <review.json> --previous <previous-review.json>
```

The validator classification is authoritative:

- `VALID` — contract and current manifest match;
- `BLOCKED_REVIEW_CONTRACT` — structural review output is invalid;
- `BLOCKED_REVIEW_CONTEXT` — output is incomplete or belongs to a different/stale manifest snapshot;
- `BLOCKED_REPEATED_FINDING` — a materially repeated finding was incorrectly declared resolved.

## Mandatory ChatGPT Project Web gate

The Web review is an independent second gate, not a confirmation of Sol.

Before Web review, generate the deterministic Web prompt from the same manifest already used for the clean Sol review:

```bash
python .specify/powerpack/bin/review_protocol.py web-prompt
```

Default output:

```text
.specify/powerpack/runtime/web-review-prompt.txt
```

Submit that exact prompt to the configured ChatGPT Project/account binding. The Web reviewer must use the Project-linked repository/GitHub context to inspect the exact manifest `head_sha`.

If the Web reviewer cannot prove access to the exact head SHA, SPEC artifacts or changed files, it MUST return `BLOCKED`. Login failure, expired browser session, missing Project access, stale Project binding or inability to reach the exact repository snapshot is never an acceptable approval path.

The Web output is validated by the same manifest-bound validator as Sol.

### Review escape

When Sol approved a snapshot but Web finds one or more defects on that **same** snapshot, record the escape before implementing anything:

```bash
python .specify/powerpack/bin/review_protocol.py record-escape \
  --sol-review <sol-review.json> \
  --web-review <web-review.json>
```

Default append-only log:

```text
.specify/powerpack/runtime/review-escapes.jsonl
```

This captures false-negative categories/severities without turning them into technical debt. The Web findings still follow the normal mandatory implementation loop.

## Final two-gate attestation

Never mark `COMPLETE` merely because both providers returned the word `APPROVED`.

Before completion, execute:

```bash
python .specify/powerpack/bin/review_protocol.py finalize \
  --sol-review <final-sol-review.json> \
  --web-review <final-web-review.json>
```

`COMPLETE` is emitted only when both reviews:

- are structurally valid;
- are valid against the current manifest;
- refer to the exact same immutable snapshot;
- both return `APPROVED`.

Any implementation change invalidates both approvals and requires a new manifest, fresh Sol review and fresh Web review.
