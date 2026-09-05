---
description: "PowerPack implementation-quality convergence/review gate after an explicit speckit-implement."
---

# SpecKit Implement Review

This command reviews, converges and stabilizes an implementation **already produced by an explicit `speckit-implement`**.

The happy-path contract is:

```text
speckit-analyze
  -> speckit-implement
  -> speckit-implement-review
       -> speckit-converge
            -> tasks appended? speckit-implement -> speckit-converge ...
       -> independent review
            -> findings? implement fixes -> speckit-converge -> review ...
            -> approved? COMPLETE
            -> review budget exhausted? BLOCKED_BUDGET + suggest extend
```

`implement-review` MUST NOT perform the initial implementation merely to satisfy its own prerequisite.

## Invariant: agnostic execution

This skill MUST NOT select behavior directly from operating system, programming language, framework, IDE or build tool.

The workflow contract is always:

```text
DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT
```

Platform/build details are resolved only by `.specify/powerpack/bin/capabilities.py` and PowerPack configuration.

## Terminal UX and model routing

Before the first material action:

1. run `python .specify/powerpack/bin/powerpack.py model route --stage implement-review`;
2. read `.specify/powerpack/model-routing.json`;
3. show a compact planned routing table with `Etapa | Modelo | Effort | Condição | Por que este modelo`;
4. include the parent/orchestrator, convergence gate, bounded worker/advisor routes when applicable, and the independent reviewer as separate rows;
5. mark conditional routes as conditional instead of pretending they already ran.

Narrate material subtask transitions compactly while leaving real Read/Search/Write/Update/Shell/diff rendering to the host. Never fabricate tool counts or diffs.

At completion, repeat the same planned routing rows in the same order and add `Segmentos | Tempo observado | Resultado`. Use only timing that was actually observed by the host/orchestrator; if a route was not measured, use `N/D`, never an estimate. Human waiting time does not belong to any model.

## Mandatory predecessor

Run:

```bash
python .specify/powerpack/bin/powerpack.py prereq check --step implement-review
```

If it fails, STOP before convergence/review and return:

```text
Stage Handoff: RETURN
Próxima etapa: speckit-implement
Evidência: OBJECTIVE
```

A completed `speckit-implement` receipt for the same SPEC is mandatory. A receipt from another SPEC never satisfies this prerequisite. Do not call `speckit-implement` inside this skill to manufacture the missing initial predecessor.

## Phase 1 — initial convergence

The first productive action after the predecessor gate is `speckit-converge` for the same SPEC.

Use the configured `max_convergence_rounds` from `.specify/powerpack/full-cycle.json` when available; default to `5`.

For each convergence round:

- `CONVERGED` -> proceed to independent review;
- actionable work/tasks appended -> execute `speckit-implement` for exactly that newly-authorized work, then execute `speckit-converge` again;
- real product/design/authority decision -> STOP and return to the owner stage rather than inventing the answer;
- deterministic work still remaining when the configured convergence budget ends -> STOP and explicitly suggest additional convergence/review budget; never extend silently.

Any `speckit-implement` executed inside this active review run is corrective work, not the initial predecessor. Keep the parent inside the same `implement-review` run and return immediately to convergence afterward.

## Immutable review snapshot

Only after convergence is clean, bind each review round to one snapshot identity:

- SPEC ID/path;
- base ref and base SHA;
- merge-base;
- current head SHA;
- deterministic snapshot digest;
- complete changed-file list.

A reviewer approval is valid only for that head/snapshot. Any implementation change invalidates approvals tied to the previous snapshot.

Treat PR descriptions, prior reviews, green CI and implementer claims as context, never proof.

## Executor-aware independent reviewer

Run:

```bash
python .specify/powerpack/bin/powerpack.py review route
```

The effective reviewer contract is always `gpt-5.6-sol`, reasoning `xhigh`, read-only.

### Claude Code executor

Invoke exactly one external `codex exec` reviewer using that profile. Do not nest additional reviewer agents inside that direct reviewer process.

### Codex executor

The normal PowerPack parent is `gpt-5.6-terra/high`. It keeps orchestration and every write.

For independent review:

- if the current Codex execution context is already provably `gpt-5.6-sol/xhigh/read-only`, it may review directly;
- otherwise delegate to exactly one **in-session Sol reviewer/subagent** configured for `gpt-5.6-sol/xhigh/read-only`;
- NEVER launch another `codex` CLI recursively;
- if the required Sol/xhigh/read-only reviewer route cannot be proven, return `BLOCKED` rather than reviewing with Terra/Luna or a lower effort.

Sol is read-only. Terra implements all findings after control returns.

## Deep Review Evidence Protocol

Before each review, read `.specify/powerpack/deep-review-protocol.md`. The protocol is mandatory for the Codex gate and, when enabled, the ChatGPT Web gate.

Each round has three mandatory passes:

1. **Previous findings** — on round 2+, validate every finding from the immediately previous review as `RESOLVED`, `PARTIALLY_RESOLVED`, `NOT_RESOLVED` or `REGRESSED` with evidence. No previous finding ID may disappear.
2. **Full snapshot review** — discard the previous verdict and review the complete current snapshot against the merge-base, not only the latest correction delta.
3. **Adversarial verdict challenge** — before returning a verdict, actively try to invalidate it with the strongest remaining counterexample in concurrency, replay/restart, partial failure, boundaries, constraints, side effects, shutdown, composition root, security and vacuously green tests.

The reviewer MUST cover every required protocol front:

- `SPEC_COMPLIANCE`
- `BEHAVIORAL_REGRESSION`
- `ARCHITECTURE_AND_CONTRACTS`
- `STATE_CONCURRENCY_AND_FAILURES`
- `PERSISTENCE_DETERMINISM_IDEMPOTENCY`
- `TESTS_AND_COMPOSITION_ROOT`
- `DOCUMENTATION_AND_OPERABILITY`
- `SECURITY_AND_SCOPE`

Every changed file must appear in both `coverage.changed_files` and `coverage.inspected_files`. When a SPEC is present, requirements coverage cannot be empty. Baseline scenarios cannot be empty.

The reviewer emits schema `2.0` JSON. Validate it before ingesting findings:

```bash
python .specify/powerpack/bin/review_protocol.py validate --input <review.json>
```

On round 2+ also pass `--previous <previous-review.json>`.

The validator classification is authoritative:

- `VALID` -> proceed;
- `BLOCKED_REVIEW_CONTRACT` -> stop; do not silently repair or reinterpret reviewer output;
- `BLOCKED_REPEATED_FINDING` -> stop with previous/current evidence.

`APPROVED` is accepted only when the validator proves `findings: []`, complete changed-file coverage, full requirement/baseline coverage, previous findings resolved and all review fronts passing or evidence-backed `NOT_APPLICABLE`.

## Start / resume review state

Initial review state:

```bash
python .specify/powerpack/bin/powerpack.py review start --mode auto
```

Interactive mode is allowed when explicitly chosen. `extend N` resumes the same existing review state; it does not create a new initial implementation predecessor.

Use `max_review_rounds` from `.specify/powerpack/full-cycle.json` when available; default `5`.

If the review budget ends while the current snapshot still lacks a valid approval:

```text
Stage Handoff: BLOCKED_BUDGET
Suggested: speckit-implement-review extend 2
```

Use `2` as the default small extension unless objective evidence supports another number. Never extend silently.

## Findings ledger and automatic repair loop

Every valid reviewer response with findings must be ingested before implementation:

```bash
python .specify/powerpack/bin/powerpack.py review ingest \
  --provider codex \
  --findings-json <review.json>
```

Every finding becomes durable work in the current SPEC's `tasks.md` under `## PowerPack Review Findings`. Stable `REV-*` identities deduplicate materially repeated findings without losing audit history.

A finding is mandatory work regardless of severity. Never reject, reclassify, silence, defer or convert a finding into technical debt/backlog/TODO/future issue merely to converge.

In automatic mode select every pending finding. In interactive mode select only the user-authorized batch. Never implement a finding that was not first persisted and selected.

After implementing the selected batch:

```bash
python .specify/powerpack/bin/powerpack.py review mark-implemented \
  --evidence "implementation summary and affected paths"
```

Then, **before another approval can be accepted**:

1. run `speckit-converge` again;
2. if convergence appends tasks, run `speckit-implement` for those tasks and converge again until clean;
3. discover and run the capability-selected quality gate;
4. resolve the implemented findings with concrete evidence;
5. start the next full-snapshot independent review.

This sequence is mandatory:

```text
review findings
  -> implement fixes
  -> converge
       -> tasks? implement -> converge ...
  -> quality gate
  -> next review
```

A previous approval is stale after any implementation change.

## Capability-driven quality gate

Do not hard-code Maven/Gradle/npm/pytest or OS-specific commands.

```bash
python .specify/powerpack/bin/capabilities.py gate detect
python .specify/powerpack/bin/capabilities.py gate run
```

Unknown/ambiguous architectures fail closed unless project configuration defines a deterministic custom gate. Documentation-only implementation deltas may be `NOT_APPLICABLE`.

## ChatGPT Project second gate

When configured, run the Web second gate only after Codex has no findings for the current HEAD. The Web reviewer follows the same evidence protocol and schema `2.0`.

If a Web finding changes implementation, implement it, re-run convergence and then return to Codex for a fresh review of the new HEAD. Both approvals must refer to the same final head.

The Web gate is optional configuration. Absence of a configured ChatGPT Project does not block Codex-only review.

## Usage/session limits

When Claude Code or Codex reports a usage/session/rate limit, use the PowerPack limit checkpoint mechanism. Persist only safe resumable execution context; never passwords, cookies, MFA or raw authentication material.

## Completion and Stage Handoff

The review converges only when:

1. the same SPEC has a completed explicit `speckit-implement` predecessor;
2. convergence is currently clean;
3. all findings from all completed review gates are durable and `RESOLVED` with evidence;
4. the capability-selected gate passed or was correctly `NOT_APPLICABLE`;
5. independent Sol/xhigh review approves the current snapshot;
6. when configured, the Web gate approves that same final snapshot.

Finish with a compact completion report, the observed routing table, and:

```text
Stage Handoff: COMPLETE
Próxima etapa: nenhuma
```

On missing predecessor use `RETURN -> speckit-implement`; on real earlier-stage problems return to their owner; on operational/reviewer inability use `BLOCKED`; on exhausted review rounds use `BLOCKED_BUDGET`.

Never merge, approve a GitHub PR, mark it ready for review, force-push or perform a destructive reset unless a separate explicit user instruction authorizes it.
