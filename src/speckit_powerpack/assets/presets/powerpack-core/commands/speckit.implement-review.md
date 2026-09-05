---
description: "PowerPack implementation-review convergence gate after speckit-implement."
---

# SpecKit Implement Review

This command is an implementation-quality convergence loop. It does not replace `speckit-converge`: `speckit-converge` checks implementation completeness against the specification; `speckit-implement-review` performs an independent technical review of the implemented snapshot.

## Mandatory predecessor

Resolve the current feature/SPEC and run:

```bash
python .specify/powerpack/bin/powerpack.py prereq check --step implement-review
```

If this fails, STOP. A completed `speckit-implement` receipt for the same SPEC is mandatory. Evidence from another SPEC never satisfies this prerequisite.

## Executor-aware reviewer routing

Run:

```bash
python .specify/powerpack/bin/powerpack.py review route
```

The returned contract is authoritative:

- **Claude Code executor** → open exactly one external `codex exec` reviewer using `gpt-5.6-sol`, `xhigh`, `read-only`.
- **Codex executor** → the current Codex session performs the review locally. Do **not** call `codex exec`, spawn another Codex session, or delegate to a custom Codex subagent.
- Unknown executor → `BLOCKED`.

The requirement is the effective reviewer profile, not the existence of a child agent named `speckit_sol_reviewer`. Never create the contradictory state where the caller forbids delegation while the reviewer protocol requires a delegation capability unavailable to the current execution mode.

The reviewer must be independent from the implementation reasoning and must inspect correctness, regressions, contracts, security, concurrency, transactionality/idempotency, data integrity, tests, operational risk, SOLID, Clean Code, and applicable GoF/design patterns. Style-only observations are findings only when they represent maintainability or correctness risk.

## Start the review run

Interactive mode is the default:

```bash
python .specify/powerpack/bin/powerpack.py review start --mode interactive
```

Fully automatic convergence:

```bash
python .specify/powerpack/bin/powerpack.py review start --mode auto
```

Optional Web second-gate configuration may be passed by the integration layer:

```text
--project-url https://chatgpt.com/g/g-p-.../project
--no-headless
```

If no ChatGPT Project is bound/configured, the review remains **Codex-only**. Do not block merely because the Web gate is absent.

## Review output and findings ledger

Every reviewer response must be normalized to JSON with a top-level `findings` list. Ingest it before implementing anything:

```bash
python .specify/powerpack/bin/powerpack.py review ingest \
  --provider codex \
  --findings-json <review.json>
```

All findings become durable tasks in the current SPEC's `tasks.md` under `## PowerPack Review Findings`. IDs are stable hashes, so a repeated finding is deduplicated rather than silently duplicated or lost.

After ingesting, show the user a compact table containing at least: ID, severity, provider, status, and title.

## Batch selection

Interactive mode: ask which pending findings should be implemented now. Then select exactly those IDs:

```bash
python .specify/powerpack/bin/powerpack.py review select --id REV-... --id REV-...
```

Auto mode: select every pending finding automatically:

```bash
python .specify/powerpack/bin/powerpack.py review select --all
```

Never implement a review finding that was not first persisted in `tasks.md` and selected for the current batch.

## Implement, test, and resolve

Implement the selected batch using the normal project conventions. After the code/docs changes for the selected findings are complete:

```bash
python .specify/powerpack/bin/powerpack.py review mark-implemented \
  --evidence "implementation summary and affected paths"
```

Then determine the project quality gate from the latest `speckit-implement`/review implementation delta:

```bash
python .specify/powerpack/bin/powerpack.py gate detect
python .specify/powerpack/bin/powerpack.py gate run
```

Rules:

- Maven is only one supported architecture; never hard-code Maven as a universal gate.
- Maven, Gradle, Node package managers, Python, .NET, Go, Rust, and an explicit custom gate are discoverable.
- Java/Eclipse without a reproducible command-line gate is `BLOCKED_CONFIGURATION`, not silently treated as Maven.
- When the relevant implementation round changed only documentation/non-executable artifacts, the quality gate is `NOT_APPLICABLE` and must not run.

After successful validation, resolve only the implemented findings and attach evidence:

```bash
python .specify/powerpack/bin/powerpack.py review resolve \
  --evidence "tests/gate and concrete resolution evidence"
```

If findings remain pending, interactive mode asks for the next batch or stops cleanly. Auto mode selects the remainder and continues.

A new review round is allowed only after all prior findings are `RESOLVED`. Any code-changing commit invalidates reviewer approvals tied to the previous HEAD and requires a fresh review.

## ChatGPT Project second gate

When a project is configured, run the assisted Web gate after the Codex gate has no findings for the current HEAD. Findings from the Web gate are ingested exactly like Codex findings and are never kept only in conversation state.

If the Web gate changes the implementation, return to Codex for a fresh independent review on the new HEAD.

## Usage/session limits

When Claude Code or Codex reports a usage/session/rate limit, classify it:

```bash
python .specify/powerpack/bin/powerpack.py limit classify --file <captured-output>
```

If it is a limit, offer the user these choices:

1. **wait-for-refresh** — persist a concise task checkpoint and safe resume argv;
2. **resume-later** — persist the same checkpoint and end the current interaction cleanly;
3. **abort** — abort the review run.

Checkpoint example:

```bash
python .specify/powerpack/bin/powerpack.py limit checkpoint \
  --executor codex \
  --summary "SPEC, PR, current round, selected findings, last gate and next action" \
  --resume-argv 'speckit-implement-review' \
  --refresh-at '<known refresh time>'
```

Never store passwords, cookies, MFA codes, or raw authentication material in the checkpoint.

## Abort

The user may abort the review at any point:

```bash
python .specify/powerpack/bin/powerpack.py review abort
```

Abort removes the local ephemeral review-run state, while intentionally preserving:

- `tasks.md` findings and their audit history;
- browser authentication profiles;
- ChatGPT Project bindings;
- versioned implementation artifacts.

Do not delete findings merely because a review was aborted.

## Completion

The implementation review converges only when:

1. the current SPEC has at least one completed `speckit-implement` predecessor;
2. every finding from every completed reviewer round is recorded in `tasks.md`;
3. every finding is `RESOLVED` with evidence;
4. the required project gate passed, or was correctly `NOT_APPLICABLE` for documentation-only work;
5. the independent Codex review approves the current HEAD;
6. when configured, the ChatGPT Project gate also approves the same current HEAD.

Never merge, approve a GitHub PR, mark it ready for review, force-push, or perform a destructive reset unless a separate explicit user instruction authorizes that action.
