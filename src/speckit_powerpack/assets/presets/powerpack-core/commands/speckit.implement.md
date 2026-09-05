---
description: "Official Spec Kit implement wrapped with PowerPack same-SPEC receipts and precise implementation delta capture."
---

## PowerPack implement preflight

Before the official implementation begins, run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage implement
python .specify/powerpack/bin/powerpack.py implement begin
```

The `begin` receipt captures a content snapshot of the worktree so files that were already dirty before this invocation are not incorrectly attributed to this implementation round.

{CORE_TEMPLATE}

## PowerPack implement completion

Only after the official command completes successfully, run:

```bash
python .specify/powerpack/bin/powerpack.py implement end
```

This records a `COMPLETED` implement receipt for the current SPEC and the precise files changed by this invocation. Never record completion on failure or interruption.
