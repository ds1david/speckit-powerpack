---
description: "Resolve the PowerPack semantic model route for a Spec Kit stage."
---

# PowerPack Model Route

Use `$ARGUMENTS` as the stage name. Run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage "$ARGUMENTS"
```

Read the JSON result. `profile` is normative PowerPack policy; `model` is an integration-specific preference. Apply the selected model only when the active agent supports safe model switching or delegated execution. Otherwise continue with the current model and report that routing was advisory rather than applied.

Never fail an SDD step solely because the current agent cannot switch models.
