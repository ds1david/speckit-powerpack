---
description: "Orchestrate one same-SPEC cycle through clarification, planning, explicit implementation and integrated convergence/review."
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

The initial `speckit-implement` is a mandatory explicit phase. `speckit-implement-review` MUST NOT be used to skip it. The integrated review skill owns its own `converge -> implement fixes -> converge -> review` loops.

## Core invariants

- Resolve exactly one SPEC at the beginning and never switch SPEC implicitly.
- Preserve `DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT`.
- Never hard-code OS, language, framework, IDE or build-tool behavior.
- Never bypass a blocked prerequisite, constitution conflict, failed gate or unresolved review finding.
- Never convert convergence/review obligations to technical debt merely to finish the cycle.
- Never merge, approve, mark ready, force-push or destructively reset as part of this workflow.
- `implement_review` requires the same-SPEC completed `implement` receipt.
- Findings and convergence gaps discovered after the initial implementation stay inside the active `implement-review` loop.

## Terminal UX and routing

Before executing the first material phase, read `.specify/powerpack/model-routing.json` and show the planned routing rows for the phases that will actually run. On Codex, the expected primary routing is Terra/high parent, Luna for bounded economical work and Sol for semantic gates/review.

Use compact progress messages when changing phases, preserve the host's native tool/diff rendering, and finish by repeating the planned routing rows with observed result/timing fields. Never fabricate timing; use `N/D` when unavailable.

## Configuration

Read `.specify/powerpack/full-cycle.json`. Projects may change enabled phases, mode and round limits, but MUST NOT weaken:

- `same_spec_only=true`;
- `stop_on_blocked=true`;
- `allow_debt_escape_hatch=false`;
- `explicit_initial_implement_required=true`;
- `implement_review_owns_convergence=true`.

Older project configs that do not yet contain the last two keys are interpreted with the safe value `true`.

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

For each current phase invoke the corresponding Spec Kit/PowerPack command for the SAME SPEC:

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

After `analyze` is clean, the state machine MUST enter `implement`.

Run `speckit-implement` completely. Its PowerPack wrapper records the same-SPEC implementation receipt. Then:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase implement \
  --outcome completed \
  --evidence "all initial tasks implemented and receipt recorded"
```

The next top-level phase is `implement_review` — not a standalone `converge` phase.

## Integrated implementation-review

Run canonical `speckit-implement-review`. It first validates the explicit implementation predecessor and then internally owns:

```text
converge
  -> tasks appended? implement -> converge ...
  -> review
       -> findings? implement fixes -> converge -> review ...
       -> approved
```

Do **not** advance the full-cycle state on an intermediate review finding or intermediate convergence gap. Continue the same `speckit-implement-review` invocation/run until it reaches a terminal handoff.

When independent review approves the current final snapshot:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase implement_review \
  --outcome approved \
  --evidence "convergence clean, gates green, reviewer(s) approved final snapshot"
```

The runtime moves to `DONE`.

If the review budget is exhausted before approval:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase implement_review \
  --outcome budget-exhausted \
  --evidence "review budget exhausted; extend required"
```

Then use `speckit-implement-review extend <N>` and resume/unblock the full-cycle state after the additional budget is explicitly authorized.

The configured `max_convergence_rounds` and `max_review_rounds` are consumed inside `speckit-implement-review`; the full-cycle runtime does not duplicate those internal loops.

## Blocking, owner-stage return and resume

If a phase is materially blocked:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase <phase> \
  --outcome blocked \
  --evidence "blocker / owner-stage handoff"
```

Use the natural owner-stage repair path: requirements/scope -> specify/clarify, design -> plan, decomposition -> tasks, implementation -> implement. After repair, re-run derived gates as necessary rather than jumping ahead based only on artifact existence.

For Claude/Codex usage limits, use the PowerPack limit checkpoint mechanism. The cycle state preserves the exact top-level phase to resume.

After a legitimate blocker or additional review budget is resolved:

```bash
python .specify/powerpack/bin/full_cycle.py resume --feature-dir <SPEC_DIR> --unblock
```

Abort removes only ephemeral cycle state:

```bash
python .specify/powerpack/bin/full_cycle.py abort --feature-dir <SPEC_DIR>
```

SPEC artifacts, implementation changes, receipts and review findings are preserved.

## Completion

`DONE` means the same SPEC passed the explicit implementation predecessor, integrated convergence, quality gates and final independent implementation review. It does NOT mean a GitHub PR is approved, ready or merged.

Report SPEC, phase history, implementation receipt, convergence/review evidence, gates, relevant task/finding IDs, unresolved blockers and final HEAD when Git is available.
