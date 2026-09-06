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

Always use:

```text
DISCOVER CAPABILITY -> SELECT STRATEGY -> EXECUTE CONTRACT
```

Do not hard-code project language/build behavior. The effective reviewer endpoint/account/Project is resolved from PowerPack user-scoped configuration.

## Mandatory PowerPack/Web readiness

Before convergence or review run:

```bash
speckit-powerpack doctor --strict-review
```

If it fails, STOP with `BLOCKED_CONFIGURATION`.

Resolve the effective reviewer identity with:

```bash
speckit-powerpack review binding show --path . --json
```

Do not infer personal reviewer state from `.specify/powerpack/review.json`. That file contains only versionable policy. Account, endpoint and Project binding are stored under the user's PowerPack config root and keyed by normalized Git repository identity.

The binding output must prove:

- repository identity/provider;
- exact Project alias/name/id/URL;
- reviewer logical profile;
- `account_label` identifying the ChatGPT account that performs Web review;
- `backend = chatgpt-web2api`;
- explicit localhost reviewer endpoint;
- valid account/Project authorization.

## Reviewer identity model

These are separate concepts:

```text
PowerPack logical profile = local reviewer identity
ChatGPT account           = account authenticated in that reviewer's dedicated Chrome profile
reviewer endpoint         = one ChatGPT-Web2API REST service for that account
Project binding           = ChatGPT Project id used for every Web review request
repository identity       = normalized Git remote, or local path when no remote exists
```

A user may intentionally maintain multiple ChatGPT Plus accounts. Example:

```text
atsel
├─ ds1david -> endpoint=http://127.0.0.1:8080 -> Plus account A
└─ webflow  -> endpoint=http://127.0.0.1:8081 -> Plus account B
```

The same ChatGPT Project may have multiple account bindings. Switching reviewer profile is explicit.

### No automatic fallback

PowerPack MUST NOT silently change reviewer profile, endpoint, ChatGPT account, Project or authentication backend after a failure.

If an endpoint/account fails during an active review, return `BLOCKED_CONFIGURATION`. Reconfiguration is an explicit user action outside the active review run.

Never silently replace the mandatory Web gate with a Codex-only completion path.

## Functional Web backend: `chatgpt-web2api`

The supported functional backend is a dedicated `ChatGPT-Web2API` service controlling a real headed Chrome profile through CDP. PowerPack communicates with that service only through its local REST contract.

PowerPack does **not** own or implement the browser automation protocol in this gate. It does not copy cookies, passwords, MFA data or OAuth tokens between personal browsers, WSL, repositories or reviewer profiles.

The browser may remain minimized during review. Headless mode is not required and is not the default because ChatGPT Web anti-bot behavior can differ in headless browsers.

Each reviewer account should use a dedicated service/profile. From WSL, PowerPack may start the service on the Windows host so Windows loopback and Chrome remain on the same OS.

## Account/service setup

Start one dedicated reviewer service:

```bash
speckit-powerpack review service start --profile <profile>
```

For multiple accounts, assign different REST/CDP ports explicitly, for example:

```bash
speckit-powerpack review service start --profile ds1david --port 8080 --cdp-port 9222
speckit-powerpack review service start --profile webflow  --port 8081 --cdp-port 9223
```

Complete ChatGPT login in the Chrome window opened for that profile, then configure the reviewer identity:

```bash
speckit-powerpack review auth configure
```

Useful checks:

```bash
speckit-powerpack review service status --endpoint http://127.0.0.1:8080
speckit-powerpack review auth list
speckit-powerpack review auth validate
speckit-powerpack review auth use <profile>
```

When an existing reviewer is selected, replacing it requires explicit confirmation. Reconfiguration invalidates previous Project bindings for that logical reviewer until the Project is re-verified.

## Project binding

After account authorization:

```bash
speckit-powerpack review project discover --profile <profile>
speckit-powerpack review project select --profile <profile> --path .
```

Known Project URL:

```bash
speckit-powerpack review project add '<project-url>' --profile <profile> --alias <alias> --path .
```

`project add` extracts the `g-p-...` Project id and verifies that the selected reviewer endpoint can actually see that Project before persisting the binding.

Switch an already registered Project/account pair:

```bash
speckit-powerpack review project use <alias> --profile <profile> --path .
```

Validate the final mapping:

```bash
speckit-powerpack review binding show --path .
```

The binding is stored under the user configuration root, not in the Git worktree.

## Terminal UX and model routing

Before the first material action:

1. run `python .specify/powerpack/bin/powerpack.py model route --stage implement-review`;
2. read `.specify/powerpack/model-routing.json`;
3. show `Etapa | Modelo | Effort | Condição | Por que este modelo`;
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

The effective reviewer contract is always `gpt-5.6-sol/xhigh/read-only`.

### Claude Code executor

Invoke exactly one external `codex exec` reviewer using that profile. Do not nest additional reviewer agents inside that reviewer process.

### Codex executor

The normal PowerPack parent is `gpt-5.6-terra/high`; Terra owns orchestration and writes.

For independent review:

- if the current Codex context is already provably `gpt-5.6-sol/xhigh/read-only`, it may review directly;
- otherwise delegate to exactly one in-session Sol reviewer/subagent configured for `gpt-5.6-sol/xhigh/read-only`;
- NEVER launch another `codex` CLI recursively;
- if the Sol route cannot be proven, return `BLOCKED`.

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

`APPROVED` requires no findings plus complete evidence/coverage required by the protocol.

## Start / resume review state

Resolve the effective binding:

```bash
speckit-powerpack review binding show --path . --json
```

Require:

```text
chatgpt_web.required = true
chatgpt_web.enabled = true
chatgpt_web.backend = chatgpt-web2api
chatgpt_web.authorization = chatgpt-web2api-project-binding
chatgpt_web.project_id = configured exact g-p-... id
chatgpt_web.project_url = configured Project URL
chatgpt_web.project_alias = configured Project alias
chatgpt_web.profile = configured reviewer profile
chatgpt_web.account_label = configured ChatGPT account identity
chatgpt_web.endpoint = configured reviewer endpoint
```

Start state with the Project URL returned by the effective binding:

```bash
python .specify/powerpack/bin/powerpack.py review start \
  --mode auto \
  --project-url <effective-project-url>
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

Build a reviewer prompt file containing:

- immutable snapshot identity;
- SPEC/relevant artifacts;
- complete changed-file/diff evidence needed by the protocol;
- previous Web findings on round 2+;
- instruction to return schema `2.0` JSON only;
- all mandatory deep-review fronts;
- explicit adversarial verdict challenge.

Send that prompt to the **bound Project id** through the configured reviewer endpoint:

```bash
speckit-powerpack review run \
  --path . \
  --prompt-file <web-review-prompt.txt> \
  --output <web-review.json>
```

Do not call another endpoint/profile/Project if this request fails. Return `BLOCKED_CONFIGURATION`.

Validate the returned review:

```bash
python .specify/powerpack/bin/review_protocol.py validate --input <web-review.json>
```

On round 2+ add `--previous <previous-web-review.json>`.

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
6. mandatory ChatGPT Project Web review through the configured Web2API endpoint approves that exact same snapshot.

Finish with:

```text
Stage Handoff: COMPLETE
Próxima etapa: nenhuma
```

Use `RETURN -> speckit-implement` for missing predecessor, owner-stage return for real earlier-stage problems, `BLOCKED` for reviewer/operational inability, `BLOCKED_CONFIGURATION` for missing/stale reviewer endpoint/account/Project state, and `BLOCKED_BUDGET` for exhausted review rounds.

Never merge, approve a GitHub PR, mark it ready, force-push or perform a destructive reset unless a separate explicit user instruction authorizes it.
