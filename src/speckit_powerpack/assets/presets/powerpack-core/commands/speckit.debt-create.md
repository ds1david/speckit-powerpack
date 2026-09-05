---
description: "Create a governed technical-debt item only when the work is legitimately deferrable."
---

# SpecKit Technical Debt — Create

Use this command to record deliberate non-blocking technical debt. It is never an escape hatch for active SPEC, convergence, review, correctness, security, compliance or data-integrity obligations.

## Effective policy

Read in order:

1. `.specify/powerpack/technical-debt-policy.md` — non-weakenable PowerPack safety floor;
2. `.specify/powerpack/technical-debt.json` — storage, prefixes and policy references;
3. every existing document listed in `project_policy_paths`.

Project rules may be stricter or add owners/domains/fields. They cannot weaken the PowerPack floor. On conflict apply the stricter rule and report it.

## Semantic creation gate

Before invoking the runtime, prove:

- work is not required by active SPEC/acceptance criteria/constitution/mandatory gate;
- it is not an unresolved `speckit-implement-review` finding;
- it is not an actionable `speckit-converge` gap;
- it is not P0/BLOCKER or an immediate correctness/security/compliance/data-integrity blocker;
- concrete evidence and impact exist;
- deferral rationale is explicit;
- objective resolution criteria exist;
- ownership is known;
- backlog was checked for duplicate/related capabilities.

If any mandatory condition fails return `NOT_DEBT`; keep the work in the flow that discovered it.

## Runtime write

Invoke the deterministic project-local ledger only after the semantic gate passes:

```bash
python .specify/powerpack/bin/debt.py create \
  --title "<title>" \
  --owner "<owner>" \
  --description "<problem>" \
  --origin "<provenance>" \
  --origin-kind <manual|spec|incident|audit> \
  --impact "<impact>" \
  --priority <P1|P2|P3 or stricter project value> \
  --resolution-criteria "<objective proof>" \
  --deferral-rationale "<why defer now>" \
  --evidence "<existing evidence>"
```

Pass `--active-obligation` or `--blocker` whenever applicable; the runtime will mechanically reject the creation. Do not disguise review/converge work as another origin kind. The runtime also rejects `origin-kind=review|converge` under the default floor.

The runtime owns canonical template creation, stable sequential ID allocation and exact-title deduplication for `markdown-v1`. If a project configures another storage format without an adapter it returns `BLOCKED_CONFIGURATION` rather than guessing.

Prefer grouping related debt into one coherent future capability. Never create one SPEC per item by default.

## Result

Return the runtime result (`CREATED`, `DUPLICATE`, `NOT_DEBT`, `BLOCKED_CONFIGURATION`, etc.) plus the semantic evidence used to decide that this work is legitimately deferrable.
