---
description: "Official Spec Kit tasks enhanced by PowerPack prerequisite enforcement."
---

## PowerPack preflight

Run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage tasks
python .specify/powerpack/bin/powerpack.py prereq check --step tasks
```

If the prerequisite check fails, STOP and execute the `next_action` returned by the runtime. Do not generate tasks from unconverged requirements.

{CORE_TEMPLATE}

## PowerPack completion receipt

After successful completion:

```bash
python .specify/powerpack/bin/powerpack.py state mark tasks --status COMPLETED
```
