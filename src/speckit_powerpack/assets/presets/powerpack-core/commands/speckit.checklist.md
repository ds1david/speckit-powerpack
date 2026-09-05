---
description: "Official Spec Kit checklist enhanced by PowerPack routing and prerequisite state."
---

## PowerPack preflight

Run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage checklist
```

Apply the route only when supported by the active integration.

{CORE_TEMPLATE}

## PowerPack completion receipt

Verify that at least one non-empty Markdown checklist exists for the current feature. Only then record:

```bash
python .specify/powerpack/bin/powerpack.py state mark checklist --status COMPLETED
```

Do not record success if checklist generation failed or produced no checklist artifact.
