# Manifest-bound Sol + ChatGPT Web review gate

## Why this exists

A local reviewer can produce a structurally valid `APPROVED` while still inspecting an incomplete subset of the SPEC or blast radius. ChatGPT Project Web can then find additional defects because it has a fresher independent pass and, in some cases, additional Project conversation context.

PowerPack now treats that situation as a measurable review escape instead of assuming the first approval was complete.

## Immutable review context

Before each fresh review round, generate:

```bash
python .specify/powerpack/bin/review_protocol.py manifest \
  --feature-dir <feature-dir>
```

The default manifest is:

```text
.specify/powerpack/runtime/review-context.json
```

It binds the round to:

- SPEC path;
- base ref/base SHA;
- merge-base;
- HEAD SHA;
- deterministic snapshot digest;
- exact changed-file set;
- all present Spec Kit artifacts;
- discovered requirement IDs;
- the context files every reviewer must inspect.

Any code/document change invalidates the manifest and every approval tied to it.

## Stronger validation

A manifest-bound `APPROVED` now requires:

- exact changed-file coverage, not just a non-empty list;
- exact requirement-ID coverage when requirements are discoverable;
- all SPEC artifacts and changed files in `coverage.inspected_files`;
- concrete `inspection_evidence` for every changed file;
- explicit adversarial `verdict_challenge`;
- `context_gaps: []`;
- all previous findings resolved;
- all existing Deep Review fronts passing.

Run:

```bash
python .specify/powerpack/bin/review_protocol.py validate \
  --input <review.json>
```

When executed from an initialized PowerPack project, the validator automatically loads the current manifest. `BLOCKED_REVIEW_CONTEXT` means the review is stale, incomplete, or does not match the immutable snapshot.

## ChatGPT Project Web gate

The Web gate must review the **same manifest** as the clean Sol gate.

Generate the deterministic prompt:

```bash
python .specify/powerpack/bin/review_protocol.py web-prompt
```

Default output:

```text
.specify/powerpack/runtime/web-review-prompt.txt
```

The prompt requires the ChatGPT Project reviewer to use its linked repository/GitHub context to prove access to the exact HEAD/base/merge-base and all manifest files. If the exact snapshot cannot be accessed, the only valid result is `BLOCKED`.

The Web review must not inherit Sol's conclusion. It receives the immutable manifest and performs a fresh full-snapshot review.

## Project-only context is not hidden truth

If the Web reviewer knows a material architectural/product constraint from Project conversation/history that is absent from repository evidence, it must return that in:

```json
"context_gaps": [
  "material constraint absent from the repository"
]
```

An approval is forbidden while `context_gaps` is non-empty. Promote that knowledge into `spec.md`, `research.md`, an ADR, architecture docs or project policy so every supported agent receives the same durable context.

## Review escape tracking

If Sol approved but Web finds defects on the same snapshot, record it before changing code:

```bash
python .specify/powerpack/bin/review_protocol.py record-escape \
  --sol-review <sol-review.json> \
  --web-review <web-review.json>
```

The default append-only log is:

```text
.specify/powerpack/runtime/review-escapes.jsonl
```

This provides objective data for categories/severities that the local reviewer misses.

## Final attestation

The workflow must not infer completion from two textual approvals. Run:

```bash
python .specify/powerpack/bin/review_protocol.py finalize \
  --sol-review <final-sol-review.json> \
  --web-review <final-web-review.json>
```

`COMPLETE` is returned only when both valid reviews approve the exact same current manifest snapshot.

## Web onboarding/readiness

Before `speckit-implement-review`, keep the existing strict readiness gate:

```bash
speckit-powerpack doctor --strict-review
```

It verifies Playwright/Chromium installation, the authorized isolated ChatGPT account profile, and the exact Project/profile binding. The actual Web review adds a second fail-closed proof: the reviewer must demonstrate access to the exact manifest snapshot. An expired login or inaccessible Project therefore cannot silently degrade into a Codex-only approval.

If onboarding is incomplete, use:

```bash
speckit-powerpack review auth authorize <profile> --account-label <label>
speckit-powerpack review project select --profile <profile> --path .
speckit-powerpack doctor --strict-review
```

For a known Project URL:

```bash
speckit-powerpack review project add \
  'https://chatgpt.com/g/g-p-.../project' \
  --profile <profile> \
  --alias <alias> \
  --path .
```

The isolated Playwright profile remains separate from Edge/Chrome and from Codex CLI authentication.
