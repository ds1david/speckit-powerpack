---
description: "Orchestrate a complete same-SPEC Spec Kit cycle through implementation, convergence and independent implementation review."
---

# SpecKit Full Cycle

This command orchestrates existing Spec Kit and PowerPack primitives. It does not duplicate their internal logic.

## Core invariants

- Resolve one SPEC at the beginning and never switch SPEC implicitly during the run.
- Preserve the PowerPack agnostic execution contract: `DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT`.
- Do not hard-code OS, language, framework, IDE or build tool behavior.
- Do not bypass a blocked prerequisite, constitution conflict, failed quality gate or unresolved review finding.
- Do not merge, approve a PR, mark it ready, force-push or perform destructive reset as part of this workflow.

## Modes

- `interactive`: pause only when a phase genuinely requires a user decision or the user chooses batch control in implement-review.
- `auto`: automatically continue through deterministic phases, convergence implementation batches and all review findings. Material ambiguity still blocks instead of being guessed.

The caller may configure maximum convergence and review rounds. Hitting a limit stops before consuming another round and preserves resumable state.

## Feature resolution

If the argument resolves an existing SPEC, use it. If no SPEC exists and the user supplied a feature description, invoke `speckit-specify` once to create it, then bind the full-cycle run to that SPEC. Never create a second SPEC automatically.

## Specification phase

Run, for the same SPEC:

1. `speckit-clarify`;
2. `speckit-plan`;
3. `speckit-checklist` when applicable;
4. `speckit-checklist-converge` only when the same-SPEC checklist predecessor actually ran;
5. `speckit-tasks`;
6. `speckit-analyze`.

A blocking inconsistency found by analyze must be resolved in the appropriate specification artifact before implementation. Do not implement around a contradictory SPEC.

## Implementation/convergence loop

Run `speckit-implement`, then `speckit-converge`.

If converge appends actionable tasks, return to `speckit-implement` for those tasks and run converge again. Continue until converge reports no remaining specified work or the configured convergence-round limit is reached.

Do not convert convergence gaps to technical debt to end the loop.

## Independent implementation-review loop

After specification convergence, run `speckit-implement-review` using its configured interactive/auto behavior.

Every review finding must enter the same-SPEC `tasks.md` review ledger and be resolved. The deep-review evidence protocol, previous-finding validation, full snapshot re-review, adversarial verdict challenge, capability-driven quality gates and optional ChatGPT Web gate are inherited from `speckit-implement-review` rather than reimplemented here.

If review changes code, the resulting head must be independently reviewed again. Completion requires approval on the current head and all durable findings resolved.

## Limits and resume

When Claude Code or Codex usage/session limits occur, reuse the PowerPack checkpoint policy. Persist the current phase, SPEC, head, convergence/review round and safe resume command. `resume-later` must not lose tasks or review findings.

## Completion report

Report SPEC ID/path, phases executed and receipts, convergence rounds, implementation-review rounds/providers, quality/closure gates and results, files/tasks materially changed, unresolved blockers and final head SHA when Git is available.

`DONE` means the SPEC artifacts converge with implementation and the independent implementation review approves the current snapshot. It does not mean a GitHub PR is approved or merged.
