---
description: "Resolve technical debt only with objective evidence against its original resolution criteria."
---

# SpecKit Technical Debt — Close

Read the PowerPack debt floor, `.specify/powerpack/technical-debt.json`, the exact item and all configured project policy documents.

Closing debt is an evidence gate. `RESOLVED` is allowed only when the original resolution criteria are objectively demonstrated under the effective policy.

## Evidence gate

For the exact ID:

1. recover the original resolution criteria; vague criteria require refinement rather than inference;
2. validate implementation/documentation/test evidence;
3. verify linked SPEC coverage rather than trusting a checkbox;
4. treat PR/commit/branch as provenance, not correctness proof;
5. when executable validation is relevant, use `.specify/powerpack/bin/capabilities.py gate run`, never a hard-coded ecosystem command;
6. prove no relevant residual remains;
7. enforce stricter project closure evidence.

If any requirement is not proven, return `NOT_CLOSABLE` and leave the item unchanged.

## Close

Only after the semantic gate passes invoke:

```bash
python .specify/powerpack/bin/debt.py close <TD-ID> \
  --criteria-satisfied \
  --evidence "<objective evidence against original criteria>" \
  --gate-status <optional PASSED|NOT_APPLICABLE>
```

The runtime refuses closure without `--criteria-satisfied` and non-empty evidence, then marks status/readiness `RESOLVED` and appends lifecycle evidence. It never deletes the item/history.

If the runtime or a project policy reports a residual, failed gate or ownership conflict, do not retry by weakening the evidence requirement.
