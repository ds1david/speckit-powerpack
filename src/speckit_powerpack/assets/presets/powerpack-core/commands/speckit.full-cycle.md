---
description: "Orchestrate one same-SPEC cycle through clarification, planning, explicit implementation and integrated convergence/dual review."
---

# SpecKit Full Cycle

This command orchestrates existing Spec Kit and PowerPack primitives. It does not duplicate their internal logic.

The top-level happy path is intentionally:

```text
speckit-clarify
  -> speckit-plan
  -> speckit-checklist
  -> speckit-checklist-converge
  -> speckit-tasks
  -> speckit-analyze
  -> speckit-implement
  -> speckit-implement-review
  -> DONE
```

`specify` normally creates/selects the SPEC before this cycle starts. It may be re-entered later only when an owner-stage handoff proves that scope/intent itself must change.

The initial `speckit-implement` is a mandatory explicit phase. `speckit-implement-review` MUST NOT be used to skip it. The integrated review skill owns its own convergence, corrective implementation, Sol/xhigh review and mandatory ChatGPT Project Web review loops.

## Core invariants

- Resolve exactly one SPEC at the beginning and never switch SPEC implicitly.
- Preserve `DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT`.
- Never bypass a blocked prerequisite, constitution conflict, failed gate or unresolved finding.
- Never convert convergence/review obligations to technical debt merely to finish the cycle.
- Never merge, approve, mark ready, force-push or destructively reset as part of this workflow.
- `implement_review` requires the same-SPEC completed `implement` receipt.
- Findings and convergence gaps discovered after the initial implementation stay inside the active `implement-review` loop.
- `implement_review` must pass `speckit-powerpack doctor --strict-review` before material review work.
- `DONE` requires Sol/xhigh and mandatory ChatGPT Project Web approval of the same final snapshot.

## Terminal UX and routing

Before executing the first material phase, read `.specify/powerpack/model-routing.json` and show the planned routing rows for the phases that will actually run. On Codex, the expected primary routing is Terra/high parent, Luna for bounded economical work, Sol for semantic gates/review, plus the mandatory Web gate.

Use compact progress messages when changing phases, preserve the host's native tool/diff rendering, and finish by repeating the planned routing rows with observed result/timing fields. Never fabricate timing; use `N/D` when unavailable.

## Configuration

Read `.specify/powerpack/full-cycle.json`. Projects may change enabled optional pre-implementation phases, mode and round limits, but MUST NOT weaken:

- `same_spec_only=true`;
- `stop_on_blocked=true`;
- `allow_debt_escape_hatch=false`;
- `explicit_initial_implement_required=true`;
- `implement_review_owns_convergence=true`.

## Start / resume state

After resolving or creating the single target SPEC:

```bash
python .specify/powerpack/bin/full_cycle.py start \
  --feature-dir <SPEC_DIR> \
  --mode <interactive|auto>
```

If a run already exists:

```bash
python .specify/powerpack/bin/full_cycle.py status --feature-dir <SPEC_DIR>
```

The returned `current_phase` is authoritative. Do not execute a later top-level phase first.

## Phase execution

| Runtime phase | Command |
|---|---|
| `clarify` | `speckit-clarify` |
| `plan` | `speckit-plan` |
| `checklist` | `speckit-checklist` when applicable |
| `checklist_converge` | `speckit-checklist-converge` |
| `tasks` | `speckit-tasks` |
| `analyze` | `speckit-analyze` |
| `implement` | `speckit-implement` |
| `implement_review` | `speckit-implement-review` |

After a normal deterministic phase succeeds:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase <phase> \
  --outcome completed \
  --evidence "concise verifiable result"
```

If checklist is not applicable, record `--outcome skipped`; the runtime also skips `checklist_converge`. Do not fake an execution receipt.

## Explicit initial implementation

After `analyze` is clean, the state machine MUST enter `implement`. Run `speckit-implement` completely and record its same-SPEC implementation receipt. The next top-level phase is `implement_review`, not a standalone `converge` phase.

## Integrated implementation-review

Before review work, `speckit-implement-review` must prove strict PowerPack readiness:

```bash
speckit-powerpack doctor --strict-review
```

Missing account consent, supported browser backend, live Windows browser session when required, exact Project binding or selected executor is a blocker, not an optional degradation to Codex-only completion.

The ChatGPT Web backend may be either:

```text
isolated-playwright
windows-browser-context
```

The active backend/profile/account stored in `.specify/powerpack/review.json` is authoritative for the Web gate. Never silently switch accounts or browser backends to make the cycle complete.

The active `implement_review` phase internally owns:

```text
converge
  -> tasks appended? implement -> converge ...
  -> Sol/xhigh review
       -> findings? implement fixes -> converge -> Sol review ...
  -> mandatory ChatGPT Project Web review
       -> findings? implement fixes -> converge -> Sol review -> Web review ...
  -> both gates approve same final snapshot
```

Do **not** advance the full-cycle state on intermediate findings or convergence gaps. Continue the same review run until it reaches a terminal handoff.

Only after dual approval:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase implement_review \
  --outcome approved \
  --evidence "convergence clean; quality gate green/N-A; Sol and Web approved same final snapshot"
```

## Review budget

If the configured budget is exhausted before dual approval, report `BLOCKED_BUDGET`, suggest an explicit extension (normally `speckit-implement-review extend 2`) and keep the top-level phase on `implement_review`.

## Blocking, owner-stage return and resume

If a phase is materially blocked:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase <phase> \
  --outcome blocked \
  --evidence "blocker / owner-stage handoff"
```

Use the natural owner-stage repair path: requirements/scope -> specify/clarify, design -> plan, decomposition -> tasks, implementation -> implement. After repair, re-run derived gates rather than jumping ahead based only on artifact existence.

For Claude/Codex usage limits, use the PowerPack limit checkpoint mechanism. After a legitimate blocker or additional review budget is resolved:

```bash
python .specify/powerpack/bin/full_cycle.py resume --feature-dir <SPEC_DIR> --unblock
```

Abort removes only ephemeral cycle state; SPEC artifacts, implementation changes, receipts and review findings are preserved.

## Completion

`DONE` means the same SPEC passed the explicit implementation predecessor, integrated convergence, quality gates, independent Sol/xhigh review and mandatory ChatGPT Project Web review on the same final snapshot under the configured reviewer account/browser backend. It does NOT mean a GitHub PR is approved, ready or merged.
