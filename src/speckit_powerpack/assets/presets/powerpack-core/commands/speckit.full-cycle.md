---
description: "Orchestrate a complete same-SPEC Spec Kit cycle through implementation, convergence and independent implementation review."
---

# SpecKit Full Cycle

This command orchestrates existing Spec Kit and PowerPack primitives. It does not duplicate their internal logic.

## Core invariants

- Resolve exactly one SPEC at the beginning and never switch SPEC implicitly.
- Preserve `DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT`.
- Never hard-code OS, language, framework, IDE or build-tool behavior.
- Never bypass a blocked prerequisite, constitution conflict, failed gate or unresolved review finding.
- Never convert convergence/review obligations to technical debt merely to finish the cycle.
- Never merge, approve, mark ready, force-push or destructively reset as part of this workflow.

## Configuration

Read `.specify/powerpack/full-cycle.json`. Projects may change enabled phases, mode and round limits, but MUST NOT weaken `same_spec_only`, `stop_on_blocked` or `allow_debt_escape_hatch=false`.

## Start / resume state

After resolving or creating the single target SPEC, start the state machine:

```bash
python .specify/powerpack/bin/full_cycle.py start \
  --feature-dir <SPEC_DIR> \
  --mode <interactive|auto>
```

If a run already exists, use:

```bash
python .specify/powerpack/bin/full_cycle.py status --feature-dir <SPEC_DIR>
```

The returned `current_phase` is authoritative. Do not execute a later phase first.

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
| `converge` | `speckit-converge` |
| `implement_review` | `speckit-implement-review` |

After a normal deterministic phase succeeds:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase <phase> \
  --outcome completed \
  --evidence "concise verifiable result"
```

If checklist is not applicable, record `--outcome skipped`; do not fake an execution receipt.

## Implementation / convergence loop

Run `speckit-implement`, then `speckit-converge`.

If converge finds actionable remaining work, it must first persist that work in the normal same-SPEC task flow, then record:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase converge \
  --outcome needs-implementation \
  --evidence "remaining task IDs / convergence evidence"
```

The runtime returns `current_phase=implement` and remembers that successful implementation must return to `converge`.

When converge proves there are no remaining implementation gaps:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase converge \
  --outcome converged \
  --evidence "convergence evidence"
```

The configured `max_convergence_rounds` is enforced by the runtime.

## Independent implementation-review loop

Run canonical `speckit-implement-review`. It inherits deep-review schema 2.0, previous-finding validation, full-snapshot review, adversarial verdict challenge, capability-driven gates and optional ChatGPT Web gate.

When valid findings exist:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase implement_review \
  --outcome findings \
  --evidence "durable REV-* finding IDs"
```

The runtime returns to `implement`; after implementation it routes back to `implement_review`. Findings remain in `tasks.md`; never move them to debt/backlog/TODO.

When independent review approves the current final snapshot:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase implement_review \
  --outcome approved \
  --evidence "approved provider(s) and final head"
```

The configured `max_review_rounds` is enforced by the runtime.

## Blocking, limits and resume

If a phase is materially blocked:

```bash
python .specify/powerpack/bin/full_cycle.py advance \
  --feature-dir <SPEC_DIR> \
  --phase <phase> \
  --outcome blocked \
  --evidence "blocker"
```

For Claude/Codex usage limits, also use the PowerPack limit checkpoint mechanism. The cycle state is already durable enough to report the exact phase to resume. After the external blocker is legitimately resolved:

```bash
python .specify/powerpack/bin/full_cycle.py resume --feature-dir <SPEC_DIR> --unblock
```

Abort removes only ephemeral cycle state:

```bash
python .specify/powerpack/bin/full_cycle.py abort --feature-dir <SPEC_DIR>
```

SPEC artifacts, implementation changes, receipts and review findings are preserved.

## Completion

`DONE` means the same SPEC converges with implementation and `speckit-implement-review` approves the current snapshot. It does NOT mean a GitHub PR is approved, ready or merged.

Report SPEC, phases/receipts, convergence and review rounds, gates, relevant task/finding IDs, unresolved blockers and final HEAD when Git is available.
