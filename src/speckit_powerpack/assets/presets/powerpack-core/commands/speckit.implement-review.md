---
description: "PowerPack implementation-quality convergence/review gate after an explicit speckit-implement."
---

# SpecKit Implement Review

This command reviews, converges and stabilizes an implementation **already produced by an explicit `speckit-implement`**.

The happy-path contract is:

```text
speckit-analyze
  -> speckit-implement
  -> speckit-implement-review
       -> speckit-converge
            -> tasks appended? speckit-implement -> speckit-converge ...
       -> Sol/xhigh independent review
            -> findings? implement fixes -> speckit-converge -> Sol review ...
       -> mandatory ChatGPT Project Web review
            -> findings? implement fixes -> speckit-converge -> Sol review -> Web review ...
            -> both gates approve same final snapshot? COMPLETE
            -> review budget exhausted? BLOCKED_BUDGET + suggest extend
```

`implement-review` MUST NOT perform the initial implementation merely to satisfy its own prerequisite.

## Invariant: agnostic execution

The workflow contract is always:

```text
DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT
```

Do not hard-code project language/build behavior. Platform/browser behavior is resolved by the PowerPack runtime/configuration.

## Mandatory PowerPack/Web readiness

Before convergence or review, run:

```bash
speckit-powerpack doctor --strict-review
```

If it fails, STOP with `BLOCKED_CONFIGURATION`.

A plain `speckit-powerpack doctor` is diagnostic and may report `SETUP`; `--strict-review` is the mandatory execution gate.

The mandatory Web gate requires:

- an account-scoped Web-review authorization;
- an exact Project alias/URL/profile binding;
- the configured `account_label` that identifies the ChatGPT account performing review;
- a supported browser backend for that account;
- live validation of the selected desktop-browser session when using `desktop-browser-context`;
- selected executor availability.

## Reviewer identity model

These are separate concepts:

```text
PowerPack logical profile = local reviewer identity
ChatGPT account           = account authenticated in the selected browser
browser                   = desktop browser carrying that account/session
Project binding           = ChatGPT Project reviewed by that account
```

A user may intentionally maintain multiple ChatGPT accounts in different browsers. Example:

```text
atsel
├─ ds1david-edge   -> account=ds1david-plus -> browser=Edge
└─ webflow-chrome  -> account=webflow-plus  -> browser=Chrome
```

The selected `Project + logical profile/account + browser backend` is authoritative for a Web review run.

### No automatic fallback

PowerPack MUST NOT silently change browser, account, profile, Project or authentication backend after a failure.

The interactive authorization UI MAY offer **`try another browser/account` only as an explicit user decision**. This is not fallback: the failed attempt persists no grant, the user chooses a new reviewer identity, and the new browser/session is validated from the beginning.

A reviewer change must therefore be visible and intentional:

```text
selected browser/account fails
  -> no grant persisted
  -> user explicitly chooses TRY ANOTHER
  -> select another browser/account
  -> authenticate
  -> grant automation permission
  -> validate session
  -> persist new reviewer authorization
```

Never automatically drop from desktop-browser context to isolated Chromium, another browser, another account or a Codex-only completion path.

## Browser backends

### `desktop-browser-context` — preferred interactive backend

PowerPack detects the runtime and browser host:

- WSL -> Windows desktop/browser host;
- Linux -> native desktop such as GNOME/KDE plus Wayland/X11 when available;
- macOS -> native browser host.

The same browser selected for the reviewer account is used from login through automation validation:

```text
select browser/account
  -> open chatgpt.com WITHOUT Playwright control
  -> complete Google/SSO/MFA in that browser
  -> explicitly grant remote-debugging/automation permission
  -> Playwright attaches to that SAME browser/session
  -> validate normal authenticated ChatGPT UI
  -> persist authorization
```

PowerPack must not copy browser cookies, passwords, MFA material, OAuth tokens or browser profile data into the repository or WSL.

Chromium-family browsers with a supported CDP attachment mechanism may be eligible. Chrome/Edge may use a recognized attach channel; Chromium-family alternatives may require an explicit CDP endpoint.

Firefox may be detected and shown to the user, but an already-running branded Firefox session is **not** to be treated as attach-compatible merely because Playwright supports launching Firefox. If no real existing-session automation backend is available, Firefox is not eligible for the automated Web gate. Fail clearly; do not fake support or switch silently.

### `isolated-playwright` — legacy/explicit configuration only

Existing explicit isolated authorizations may remain readable for migration compatibility. They are never an automatic fallback from desktop-browser authorization failure.

## Account setup

Primary setup is interactive:

```bash
speckit-powerpack review auth configure
```

Reconfiguration is also interactive:

```bash
speckit-powerpack review auth reconfigure
```

When an existing valid grant is selected, the CLI must ask whether to replace it. Declining preserves the existing authorization unchanged.

A reconfiguration that changes browser/account invalidates previous Project bindings for that logical reviewer until the Project is re-verified.

List/select accounts with:

```bash
speckit-powerpack review auth list
speckit-powerpack review auth use <profile>
speckit-powerpack review auth validate <profile>
```

## Project binding

After account authorization, discover/select a Project:

```bash
speckit-powerpack review project discover --profile <profile>
speckit-powerpack review project select --profile <profile> --path .
```

Known/shared Project URL:

```bash
speckit-powerpack review project add '<project-url>' --profile <profile> --alias <alias> --path .
```

Invite/shared link:

```bash
speckit-powerpack review project accept-invite '<invite-or-shared-link>' --profile <profile> --alias <alias> --path .
```

Switch an already registered Project/account pair:

```bash
speckit-powerpack review project use <alias> --profile <profile> --path .
```

The same Project may have multiple account bindings. Switching the profile changes the Web reviewer identity and must be explicit.

## Terminal UX and model routing

Before the first material action:

1. run `python .specify/powerpack/bin/powerpack.py model route --stage implement-review`;
2. read `.specify/powerpack/model-routing.json`;
3. show a compact planned routing table with `Etapa | Modelo | Effort | Condição | Por que este modelo`;
4. include parent/orchestrator, convergence, Sol reviewer and mandatory Web gate as separate rows;
5. mark conditional routes as conditional.

Never fabricate tool counts, diffs or timing. At completion repeat the planned rows and add observed result/timing fields; use `N/D` when timing was not measured.

## Mandatory predecessor

Run:

```bash
python .specify/powerpack/bin/powerpack.py prereq check --step implement-review
```

If it fails, STOP before convergence/review and return:

```text
Stage Handoff: RETURN
Próxima etapa: speckit-implement
Evidência: OBJECTIVE
```

A completed `speckit-implement` receipt for the same SPEC is mandatory. A receipt from another SPEC never satisfies this prerequisite. Do not call `speckit-implement` inside this skill to manufacture the missing initial predecessor.

## Phase 1 — initial convergence

The first productive action after readiness and predecessor gates is `speckit-converge` for the same SPEC.

Use `max_convergence_rounds` from `.specify/powerpack/full-cycle.json` when available; default `5`.

For each convergence round:

- `CONVERGED` -> proceed to independent Sol review;
- tasks appended -> run `speckit-implement` for exactly that newly-authorized work, consume its internal receipt when required, then converge again;
- real product/design/authority decision -> STOP and return to the owner stage;
- deterministic work remaining when the configured budget ends -> STOP; never extend silently.

Corrective `speckit-implement` calls inside an active review run do not replace the mandatory initial predecessor.

## Immutable review snapshot

Only after convergence is clean, bind each review round to one snapshot identity:

- SPEC ID/path;
- base ref/base SHA;
- merge-base;
- current head SHA;
- deterministic snapshot digest;
- complete changed-file list.

Any implementation change invalidates approvals tied to the previous snapshot.

## Executor-aware independent Sol reviewer

Run:

```bash
python .specify/powerpack/bin/powerpack.py review route
```

The effective reviewer contract is always `gpt-5.6-sol`, reasoning `xhigh`, read-only.

### Claude Code executor

Invoke exactly one external `codex exec` reviewer using that profile. Do not nest additional reviewer agents inside that reviewer process.

### Codex executor

The normal PowerPack parent is `gpt-5.6-terra/high`; Terra owns orchestration and writes.

For independent review:

- if the current Codex context is already provably `gpt-5.6-sol/xhigh/read-only`, it may review directly;
- otherwise delegate to exactly one in-session Sol reviewer/subagent configured for `gpt-5.6-sol/xhigh/read-only`;
- NEVER launch another `codex` CLI recursively;
- if the Sol/xhigh/read-only route cannot be proven, return `BLOCKED`.

Sol is read-only. Terra implements findings after control returns.

## Deep Review Evidence Protocol

Before each Sol or Web review, read `.specify/powerpack/deep-review-protocol.md`.

Each round requires:

1. previous-finding validation on round 2+;
2. full current-snapshot review against merge-base;
3. adversarial verdict challenge.

Required fronts:

- `SPEC_COMPLIANCE`
- `BEHAVIORAL_REGRESSION`
- `ARCHITECTURE_AND_CONTRACTS`
- `STATE_CONCURRENCY_AND_FAILURES`
- `PERSISTENCE_DETERMINISM_IDEMPOTENCY`
- `TESTS_AND_COMPOSITION_ROOT`
- `DOCUMENTATION_AND_OPERABILITY`
- `SECURITY_AND_SCOPE`

Reviewer output uses schema `2.0`. Validate it:

```bash
python .specify/powerpack/bin/review_protocol.py validate --input <review.json>
```

On round 2+ add `--previous <previous-review.json>`.

Authoritative classifications:

- `VALID` -> proceed;
- `BLOCKED_REVIEW_CONTRACT` -> stop;
- `BLOCKED_REPEATED_FINDING` -> stop with evidence.

`APPROVED` requires no findings plus complete evidence/coverage required by the protocol.

## Start / resume review state

Read `.specify/powerpack/review.json` and require:

```text
chatgpt_web.required = true
chatgpt_web.enabled = true
chatgpt_web.authorization = playwright-account-consent
chatgpt_web.project_url = configured exact Project URL
chatgpt_web.project_alias = configured local Project alias
chatgpt_web.profile = configured reviewer logical profile
chatgpt_web.account_label = configured ChatGPT account identity
chatgpt_web.account_backend = desktop-browser-context | isolated-playwright
```

For `desktop-browser-context`, also require the persisted host/browser attachment data and a live session check from `doctor --strict-review`.

Do not silently substitute another account/browser even if it has access to the same Project.

Start state:

```bash
python .specify/powerpack/bin/powerpack.py review start \
  --mode auto \
  --project-url <configured-project-url>
```

`extend N` resumes the same review state; it does not create a new initial predecessor.

Use `max_review_rounds` from `.specify/powerpack/full-cycle.json` when available; default `5`.

On budget exhaustion:

```text
Stage Handoff: BLOCKED_BUDGET
Suggested: speckit-implement-review extend 2
```

Never extend silently.

## Findings ledger and repair loop

Ingest every valid review with findings before implementation:

```bash
python .specify/powerpack/bin/powerpack.py review ingest \
  --provider <codex|chatgpt-web> \
  --findings-json <review.json>
```

All findings are mandatory work regardless of severity. Do not defer findings to debt/backlog/TODO merely to converge.

After implementation:

```bash
python .specify/powerpack/bin/powerpack.py review mark-implemented \
  --evidence "implementation summary and affected paths"
```

Then always:

```text
review findings
  -> implement fixes
  -> converge
       -> tasks? implement -> converge ...
  -> capability-selected quality gate
  -> fresh Sol review
  -> fresh Web review
```

A previous approval is stale after any implementation change.

## Capability-driven quality gate

Do not hard-code Maven/Gradle/npm/pytest or OS-specific commands.

```bash
python .specify/powerpack/bin/capabilities.py gate detect
python .specify/powerpack/bin/capabilities.py gate run
```

Unknown/ambiguous architectures fail closed unless project configuration defines a deterministic custom gate. Documentation-only deltas may be `NOT_APPLICABLE` when correctly justified.

## Mandatory ChatGPT Project Web gate

Run Web review only after Sol has no findings for the current snapshot.

Use only the exact reviewer identity from `.specify/powerpack/review.json`:

```text
profile + account_label + account_backend + browser/host + Project alias/URL
```

For `desktop-browser-context`, attach to the configured running browser instance after explicit user authorization. Use the existing authenticated context in place; never export cookies or credential material.

If the live attach/session check fails, return `BLOCKED_CONFIGURATION`. Do not silently switch browser/account/backend.

An explicit user-triggered `try another browser/account` belongs to **authorization/reconfiguration**, not to an active review run. After reconfiguration, revalidate the Project binding and restart the Web gate under the newly selected reviewer identity.

If Web produces findings:

```text
Web finding
  -> persist finding
  -> Terra/implementer fixes
  -> converge until clean
  -> quality gate
  -> fresh Sol review
  -> fresh Web review
```

Both final approvals must refer to the same final snapshot.

## Completion

The review converges only when:

1. same-SPEC explicit initial `speckit-implement` predecessor is proven;
2. convergence is currently clean;
3. all findings are `RESOLVED` with evidence;
4. capability-selected quality gate passed or is correctly `NOT_APPLICABLE`;
5. independent Sol/xhigh review approves the current snapshot;
6. mandatory ChatGPT Project Web review, under the configured account/browser/Project identity, approves that exact same snapshot.

Finish with:

```text
Stage Handoff: COMPLETE
Próxima etapa: nenhuma
```

Use `RETURN -> speckit-implement` for missing predecessor, owner-stage return for real earlier-stage problems, `BLOCKED` for reviewer/operational inability, `BLOCKED_CONFIGURATION` for missing/stale Web account/browser/Project state, and `BLOCKED_BUDGET` for exhausted review rounds.

Never merge, approve a GitHub PR, mark it ready, force-push or perform a destructive reset unless a separate explicit user instruction authorizes it.
