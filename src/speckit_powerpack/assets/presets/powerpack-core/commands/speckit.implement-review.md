---
description: "PowerPack implementation-review convergence gate after speckit-implement."
---

# SpecKit Implement Review

This command is an implementation-quality convergence loop. It complements `speckit-converge`: convergence checks completeness against the specification; implement-review performs an independent technical review of the implemented snapshot.

## Invariant: agnostic execution

This skill MUST NOT select behavior directly from operating system, programming language, framework, IDE or build tool.

The workflow contract is always:

```text
DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT
```

Platform/build details are resolved only by:

```bash
python .specify/powerpack/bin/capabilities.py ...
```

Do not introduce branches such as `if Windows`, `if Java`, `if Maven`, `if Node`, or equivalent into this skill. Adding support for another ecosystem means adding a capability strategy, not changing review semantics.

## Mandatory predecessor

Run:

```bash
python .specify/powerpack/bin/powerpack.py prereq check --step implement-review
```

If it fails, STOP. A completed `speckit-implement` receipt for the same SPEC is mandatory. A receipt from another SPEC never satisfies this prerequisite.

## Immutable review snapshot

Every review round MUST bind itself to one snapshot identity before asking any reviewer to judge the code:

- SPEC ID/path;
- base ref and base SHA;
- merge-base;
- current head SHA;
- deterministic snapshot digest;
- complete changed-file list.

A reviewer approval is valid only for that head/snapshot. Any code-changing commit invalidates all approvals tied to the previous head.

Treat PR descriptions, prior reviews, green CI and implementer claims as context, never proof.

## Executor-aware independent reviewer

Run:

```bash
python .specify/powerpack/bin/powerpack.py review route
```

The returned route is authoritative:

- Claude Code executor -> invoke exactly one external `codex exec` reviewer using the declared reviewer profile;
- Codex executor -> the current Codex session is the reviewer and MUST NOT invoke another Codex session/subagent;
- unknown executor -> `BLOCKED`.

For the current deep-review profile the expected Codex contract is `gpt-5.6-sol`, reasoning effort `xhigh`, sandbox `read-only`.

The requirement is the effective reviewer profile, not unconditional spawning of a custom child agent. Never recreate the contradictory state where the caller forbids delegation but the reviewer protocol requires a delegation mechanism unavailable to the execution mode.

## Deep Review Evidence Protocol

Before each review, read `.specify/powerpack/deep-review-protocol.md`. The protocol is mandatory for both the Codex gate and, when enabled, the ChatGPT Web gate.

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
python .specify/powerpack/bin/review_protocol.py validate \
  --input <review.json>
```

On round 2+:

```bash
python .specify/powerpack/bin/review_protocol.py validate \
  --input <review.json> \
  --previous <previous-review.json>
```

The validator classification is authoritative:

- `VALID` -> proceed;
- `BLOCKED_REVIEW_CONTRACT` -> stop; do not silently repair, soften or reinterpret the reviewer output;
- `BLOCKED_REPEATED_FINDING` -> stop with the previous/current evidence because a finding declared resolved materially reappeared.

`APPROVED` is accepted only when the validator proves:

- `findings: []`;
- every changed file was inspected;
- no requirement is `PARTIAL`/`FAIL`;
- no baseline scenario is `REGRESSION`;
- every previous finding is `RESOLVED`;
- every review front is `PASS` or evidence-backed `NOT_APPLICABLE`.

## Start

Interactive mode:

```bash
python .specify/powerpack/bin/powerpack.py review start --mode interactive
```

Automatic convergence:

```bash
python .specify/powerpack/bin/powerpack.py review start --mode auto
```

The integration layer may also pass a configured ChatGPT Project URL and headed/headless preference. If no ChatGPT Project is configured, the review remains Codex-only and MUST NOT block merely because the Web second gate is absent.

## Findings ledger

Every valid reviewer response with findings must be ingested before implementation:

```bash
python .specify/powerpack/bin/powerpack.py review ingest \
  --provider codex \
  --findings-json <review.json>
```

Every finding becomes durable work in the current SPEC's `tasks.md` under `## PowerPack Review Findings`. Stable `REV-*` identities deduplicate repeated material findings without losing audit history.

A finding is mandatory work regardless of severity. Never reject, reclassify, silence, defer or convert a review finding into technical debt/backlog/TODO/future issue merely to converge.

Show a compact table containing ID, severity, provider, status and title.

## Batch selection

Interactive mode selects only the findings chosen by the user:

```bash
python .specify/powerpack/bin/powerpack.py review select --id REV-... --id REV-...
```

Automatic mode selects every pending finding:

```bash
python .specify/powerpack/bin/powerpack.py review select --all
```

Never implement a review finding that was not first persisted in `tasks.md` and selected for the active batch.

## Implement and record evidence

After implementing the selected batch:

```bash
python .specify/powerpack/bin/powerpack.py review mark-implemented \
  --evidence "implementation summary and affected paths"
```

## Architecture- and OS-agnostic quality gate

Do NOT call a hard-coded Maven, Gradle, npm, pytest or OS-specific command.

Discover the gate through the capability resolver:

```bash
python .specify/powerpack/bin/capabilities.py gate detect
```

Then execute exactly the returned strategy through:

```bash
python .specify/powerpack/bin/capabilities.py gate run
```

Rules enforced by the resolver:

- Windows/Linux/macOS differences are implementation details behind platform capabilities;
- Maven/Gradle wrappers resolve to the native executable variant without changing workflow semantics;
- build strategies are detected from reproducible project descriptors, not guessed from source language;
- `pyproject.toml` alone does not imply pytest;
- Eclipse metadata does not imply Maven;
- missing required build executables produce `BLOCKED_CONFIGURATION`;
- multiple simultaneously detected build strategies are ambiguous and require explicit `custom_command` instead of a silent choice;
- unknown architectures require an explicit custom gate;
- documentation-only implementation rounds are `NOT_APPLICABLE` on every OS/framework and do not execute an application build gate.

A user/project-provided `custom_command` is an argv list and has precedence over automatic strategy discovery.

## Resolve findings

Only after successful validation:

```bash
python .specify/powerpack/bin/powerpack.py review resolve \
  --evidence "gate/tests and concrete resolution evidence"
```

If pending findings remain, interactive mode asks for the next batch or stops cleanly; auto mode selects the remainder and continues. A new review round is allowed only after every finding from the previous round is `RESOLVED`.

## ChatGPT Project second gate

When configured, run the Web second gate only after Codex has no findings for the current HEAD.

The Web reviewer follows the same deep-review evidence protocol and schema `2.0`; it does not inherit trust from the Codex approval. Validate its JSON with `review_protocol.py` before ingestion.

ChatGPT browser authentication is **platform-scoped**. Windows, Linux/WSL and macOS use separate persistent-profile namespaces even when the human-readable profile name is identical. A project binding is also resolved for the current platform; never reuse a Windows profile directory from Linux/WSL or macOS, or vice versa.

If a Web finding changes implementation, return to Codex for a fresh review of the new HEAD. Both approvals must refer to the same final head.

## Usage/session limits

When Claude Code or Codex reports a usage/session/rate limit, classify it:

```bash
python .specify/powerpack/bin/powerpack.py limit classify --file <captured-output>
```

Offer:

1. `wait-for-refresh` -> persist a concise task checkpoint and safe resume argv;
2. `resume-later` -> persist the checkpoint and end cleanly;
3. `abort` -> abort only the current review execution.

Never persist passwords, cookies, MFA codes or raw authentication material.

## Abort

```bash
python .specify/powerpack/bin/powerpack.py review abort
```

Abort removes ephemeral review-run state while preserving:

- durable `tasks.md` findings/history;
- platform-scoped browser authentication profiles;
- platform-scoped ChatGPT Project bindings;
- versioned implementation artifacts.

## Completion

The review converges only when:

1. the same SPEC has at least one completed `speckit-implement` predecessor;
2. all findings from all completed review gates are recorded in `tasks.md`;
3. all findings are `RESOLVED` with evidence;
4. the capability-selected gate passed or was correctly `NOT_APPLICABLE` for docs-only work;
5. independent Codex deep review validates and approves the current HEAD;
6. when configured, the ChatGPT Project deep-review gate validates and approves that same HEAD.

Never merge, approve a GitHub PR, mark it ready for review, force-push or perform a destructive reset unless a separate explicit user instruction authorizes it.
