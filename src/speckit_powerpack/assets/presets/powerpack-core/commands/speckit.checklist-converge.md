---
description: "Converge requirements-quality checklists after a completed speckit-checklist for the same SPEC."
---

# SpecKit Checklist Converge

Run first:

```bash
python .specify/powerpack/bin/powerpack.py prereq check --step checklist-converge
```

If the current SPEC does not have a `COMPLETED` `speckit-checklist` receipt, STOP. The mere existence of a checklist file is not sufficient predecessor evidence.

Revalidate every checklist item as a requirements-writing quality test. This command evaluates the specification/plan/supporting requirements documents, **not application code**. Do not pass/fail a checklist item from implementation code or tests.

Authority order: constitution > explicit user decisions > spec > plan > supporting requirements docs > tasks > checklist.

Classify each item as `SATISFIED`, `RESOLVABLE_GAP`, `BLOCKED_DECISION`, `INVALIDATED`, or `STRUCTURAL_GAP`. Deterministic documentation gaps may be repaired. New product/security/UX/business intent must remain `BLOCKED_DECISION`.

Never modify application code or application tests. If requirements docs change after `tasks.md` exists, report `TASKS_STALE: true`; do not silently rewrite tasks.

When all applicable checklist items converge, mark:

```bash
python .specify/powerpack/bin/powerpack.py state mark checklist-converge --status CONVERGED
```
