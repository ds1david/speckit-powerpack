# SpecKit PowerPack

> **Status: Draft / pre-release.** The repository is intentionally evolving before its first stable public release.

SpecKit PowerPack is a composable enhancement layer for the official [GitHub Spec Kit](https://github.com/github/spec-kit). It does **not** fork or replace Spec Kit. It uses Spec Kit-native presets/extensions and adds reusable workflow state, convergence, deep implementation review, full-cycle orchestration, technical-debt governance, executor-aware model routing and managed updates.

## Current happy path

PowerPack preserves the first implementation as an explicit mandatory stage:

```text
speckit-specify
  -> speckit-clarify
  -> speckit-plan
  -> speckit-checklist
  -> speckit-checklist-converge
  -> speckit-tasks
  -> speckit-analyze
  -> speckit-implement
  -> speckit-implement-review
       -> speckit-converge
            -> tasks appended? speckit-implement -> speckit-converge ...
       -> independent Sol review
            -> findings? implement fixes -> speckit-converge -> review ...
       -> mandatory ChatGPT Project Web review
            -> findings? implement fixes -> speckit-converge -> Sol review -> Web review ...
            -> same final snapshot approved by both gates? COMPLETE
            -> review budget exhausted? BLOCKED_BUDGET -> explicit extend
```

`speckit-implement-review` cannot be used to skip the initial `speckit-implement`. Its first productive action after validating the same-SPEC implementation predecessor is convergence.

## What this draft adds

- `speckit-checklist-converge` with same-SPEC predecessor enforcement.
- `speckit-implement` wrapper with precise before/after workspace delta receipts.
- explicit `speckit-implement -> speckit-implement-review` predecessor contract.
- `speckit-converge` integration with PowerPack state.
- one canonical `speckit-implement-review` that owns convergence/review/fix/re-convergence after the initial implementation.
- Deep Review Evidence Protocol: immutable snapshot identity, requirements/baseline coverage, previous-finding validation, full-snapshot re-review and adversarial verdict challenge.
- review schema 2.0 validator with `BLOCKED_REVIEW_CONTRACT` and `BLOCKED_REPEATED_FINDING`.
- durable review findings in `tasks.md`: `PENDING → SELECTED → IMPLEMENTED → RESOLVED`.
- explicit review budget handling with `BLOCKED_BUDGET` and user-authorized `extend N`.
- `speckit-full-cycle` with a resumable same-SPEC top-level state machine ending in the integrated implementation-review stage.
- governed technical-debt lifecycle: `speckit-debt-create`, `list`, `consult`, `start`, `close` plus a deterministic project-local ledger runtime.
- debt safety floor forbidding active SPEC work, convergence gaps, review findings and blockers from becoming deferred debt.
- architecture/OS/language/framework/build-tool agnostic capability resolution.
- Claude Code / Codex executor-aware reviewer routing without recursive Codex CLI spawning.
- Codex-first model routing: Terra parent, Luna bounded worker, Sol semantic gate/advisor/reviewer.
- mandatory ChatGPT Project Web second gate using a PowerPack-owned isolated Playwright Chromium profile.
- explicit browser consent scoped to the selected ChatGPT Project; Windows Edge/Chrome state is never reused.
- compatible Spec Kit bootstrap/upgrade to the tested release when an older CLI is installed.
- confirmed self/project update management plus explicit forced recovery.
- usage/session-limit checkpoints and resumable execution.
- cross-platform CI for non-draft PRs and `main`.

## Core design rule

Workflow logic must not scatter assumptions about operating system, language, framework, IDE or build tool:

```text
DISCOVER CAPABILITY
        ↓
SELECT STRATEGY
        ↓
EXECUTE CONTRACT
```

Project-specific rules complement PowerPack through configuration, policy, closure gates and local skills rather than cloning PowerPack skills.

## Architecture

```mermaid
flowchart TB
    U[Developer / AI agent] --> CLI[speckit-powerpack CLI]
    CLI --> SK[Official GitHub Spec Kit]
    CLI --> PRE[powerpack-core Preset]
    CLI --> EXT[powerpack-tools Extension]

    PRE --> IMP[speckit-implement wrapper]
    PRE --> CONV[speckit-converge wrapper]
    PRE --> REV[speckit-implement-review]
    PRE --> FULL[speckit-full-cycle]
    PRE --> DEBT[technical-debt lifecycle]

    EXT --> DOC[doctor]
    EXT --> UPD[confirmed update/recovery]

    CLI --> RT[Project-local Python runtimes]
    CLI --> PW[isolated Playwright Chromium consent/profile]
    RT --> STATE[same-SPEC receipts/review ledger]
    RT --> CAP[capability resolver]
    RT --> RP[review protocol validator]
    RT --> FC[full-cycle state machine]
    RT --> TD[technical-debt ledger]
    PW --> WEB[ChatGPT Project Web gate]
```

Generated `.claude/skills/*` and `.agents/skills/*` files are materialized views, not the durable customization source.

## Requirements

- Python 3.11+
- Git
- `uv` when PowerPack must bootstrap Spec Kit or self-update
- official Spec Kit `>=1.0.0` (the installer can upgrade to the tested `v1.0.4`)
- Claude Code and/or Codex CLI
- Playwright + Chromium for the mandatory ChatGPT Project Web gate; Playwright is a core package dependency and Chromium is prepared by installation/setup

Claude Code is **not required** for a Codex-first PowerPack execution.

## Model routing

### Codex-first defaults

When `.specify/powerpack/model-routing.json` has `active_integration: "codex"`:

| Role | Model | Effort | Authority |
|---|---|---:|---|
| Parent / orchestrator / implementer | `gpt-5.6-terra` | high | writes, phase ownership, user interaction |
| Bounded mechanical worker | `gpt-5.6-luna` | medium | narrow scans, inventories and evidence collection |
| Semantic gate / advisor | `gpt-5.6-sol` | high | read-only semantic escalation |
| Independent deep reviewer | `gpt-5.6-sol` | xhigh | read-only review |

The independent reviewer contract remains:

```text
gpt-5.6-sol / xhigh / read-only
```

A Terra parent must **not** launch another `codex` CLI recursively. Review uses either the current context when it is already provably Sol/xhigh/read-only or exactly one in-session Sol reviewer/subagent with that contract. If that route cannot be proven, review returns `BLOCKED` instead of silently downgrading.

### Claude defaults

Claude Code keeps Sonnet as the parent/implementer, Haiku for bounded economical work, Opus only as a conditional advisor, and external Codex Sol/xhigh as the independent deep reviewer.

## Installation

### Install the CLI from current `main`

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@main
```

### New project

Claude:

```bash
mkdir my-project
cd my-project
speckit-powerpack init . --integration claude
```

Codex:

```bash
mkdir my-project
cd my-project
speckit-powerpack init . --integration codex
```

### Existing Spec Kit project — Codex primary

```bash
cd /path/to/existing-project

git status --short
git branch --show-current

uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@main

speckit-powerpack install . --integration codex --bootstrap-speckit
```

`--bootstrap-speckit` is also the supported upgrade path when an older incompatible Spec Kit already exists. PowerPack detects the installed version and upgrades it to the tested release instead of allowing the preset installation to fail later with a compatibility error.

Installation materializes the PowerPack and prepares Playwright/Chromium, but **does not silently grant Web access**. Review readiness requires one explicit consent operation:

```bash
speckit-powerpack review authorize \
  --profile atsel \
  --project atsel \
  --url 'https://chatgpt.com/g/g-p-.../project' \
  --path .
```

That command opens a visible PowerPack Chromium window. The first tab explains the requested scope and asks for permission. If authorized, the selected ChatGPT Project opens in a second tab; credentials/MFA are entered only on `chatgpt.com`. Return to the consent tab and grant access only after confirming the correct Project.

Finally:

```bash
speckit-powerpack doctor
```

`doctor` is not green until Spec Kit compatibility, executor availability, Playwright browser preparation, explicit Playwright consent and the exact Project binding are all present.

Then inspect:

```bash
cat .specify/powerpack/model-routing.json
cat .specify/powerpack/full-cycle.json
cat .specify/powerpack/prerequisites.json
cat .specify/powerpack/review.json
```

Expected core values include:

```text
active_integration = codex
implement            -> gpt-5.6-terra/high
full-cycle           -> gpt-5.6-terra/high
implement-review     -> gpt-5.6-terra/high parent
convergence semantic gate -> gpt-5.6-sol/high
independent reviewer -> gpt-5.6-sol/xhigh/read-only
chatgpt_web.required = true
chatgpt_web.authorization = playwright-consent
```

For the full migration/checklist, see [`docs/CODEX_FIRST_INSTALL.md`](docs/CODEX_FIRST_INSTALL.md).

### What installation replaces or wraps

PowerPack uses Spec Kit preset strategies instead of blindly copying an old `.claude/skills` or `.agents/skills` tree:

- **wraps** official `speckit-implement`;
- **wraps** official `speckit-converge`;
- **replaces/owns** `speckit-checklist-converge`;
- **replaces/owns** `speckit-implement-review`;
- **replaces/owns** `speckit-full-cycle`;
- **replaces/owns** PowerPack technical-debt lifecycle commands.

This rematerializes the enhanced generated skills for the selected integration while preserving unrelated project-owned skills.

## Installed project layout

```text
.specify/
└── powerpack/
    ├── bin/
    │   ├── powerpack.py
    │   ├── capabilities.py
    │   ├── review_protocol.py
    │   ├── debt.py
    │   └── full_cycle.py
    ├── model-routing.json
    ├── prerequisites.json
    ├── quality-gates.json
    ├── review.json
    ├── full-cycle.json
    ├── technical-debt.json
    ├── update.json
    ├── deep-review-protocol.md
    ├── technical-debt-policy.md
    ├── technical-debt-template.md
    ├── state/                     # durable same-SPEC receipts
    └── runtime/                   # gitignored resumable/ephemeral execution state
        ├── reviews/
        ├── full-cycle/
        └── limit-checkpoint.json
```

Machine-local browser state lives outside the repository:

```text
<global PowerPack config>/
├── browser-install/<platform>.json
└── browser-profiles/
    ├── windows/<profile>/
    ├── linux/<profile>/
    └── macos/<profile>/
```

The PowerPack profile is intentionally independent from regular Windows Edge/Chrome profiles.

## Same-SPEC workflow safety

PowerPack does not treat artifact existence as proof that a predecessor actually ran.

```mermaid
flowchart LR
    C[speckit-checklist / SPEC-A] --> CR[receipt SPEC-A]
    CR --> CC[speckit-checklist-converge / SPEC-A]
    CR -. invalid .-> CCB[checklist-converge / SPEC-B]

    I[speckit-implement / SPEC-A] --> IR[completed implement receipt SPEC-A]
    IR --> R[speckit-implement-review / SPEC-A]
    IR -. invalid .-> RB[implement-review / SPEC-B]
```

The implement wrapper also snapshots workspace content. A file already dirty before the round is not attributed to that implementation round unless its contents change again.

The full-cycle safety floor requires:

```json
{
  "same_spec_only": true,
  "stop_on_blocked": true,
  "allow_debt_escape_hatch": false,
  "explicit_initial_implement_required": true,
  "implement_review_owns_convergence": true
}
```

## Capability-driven quality gates

No universal Maven/Gradle/npm/pytest command is embedded in workflow skills. The installed `capabilities.py` discovers a reproducible strategy and fails closed on unknown/ambiguous architecture. Documentation-only implementation deltas are `NOT_APPLICABLE`.

Project override lives in `.specify/powerpack/quality-gates.json`.

See [`docs/PORTABILITY.md`](docs/PORTABILITY.md).

## Canonical `speckit-implement-review`

There is exactly one canonical asset: `speckit.implement-review.md`.

```mermaid
flowchart TD
    PRE[Validate same-SPEC implement predecessor] --> CONV[Run convergence]
    CONV -->|tasks appended| IMP[Implement appended work]
    IMP --> CONV
    CONV -->|clean| SNAP[Bind SPEC/base/merge-base/head/digest]
    SNAP --> PREV[Validate previous findings]
    PREV --> FULL[Sol review full current snapshot]
    FULL --> ADV[Adversarial verdict challenge]
    ADV --> JSON[Schema 2.0 evidence JSON]
    JSON --> VAL[review_protocol.py]
    VAL -->|invalid| BC[BLOCKED_REVIEW_CONTRACT]
    VAL -->|findings| TASKS[Persist REV-* in tasks.md]
    TASKS --> FIX[Implement selected/all batch]
    FIX --> CONV2[Re-converge]
    CONV2 --> GATE[Capability-selected gate]
    GATE --> SNAP
    VAL -->|Sol approved| WEB[Mandatory ChatGPT Project Web gate same HEAD]
    WEB -->|findings| TASKS
    WEB -->|approved same HEAD| DONE[COMPLETE]
```

Findings can never be converted to debt/backlog/TODO merely to force convergence. Any implementation change invalidates earlier approvals and restarts convergence before a fresh Sol review; Web review runs only after the current Sol review is clean.

If the configured review budget is exhausted before both gates approve, the skill reports `BLOCKED_BUDGET` and recommends an explicit extension such as:

```text
speckit-implement-review extend 2
```

See [`docs/IMPLEMENT_REVIEW.md`](docs/IMPLEMENT_REVIEW.md).

## `speckit-full-cycle`

The full-cycle state machine controls only top-level SDD phases:

```text
clarify
→ plan
→ checklist/checklist-converge
→ tasks
→ analyze
→ implement
→ implement-review
→ DONE
```

`implement-review` internally owns convergence, corrective implementation and both review gates. Intermediate findings do not bounce the top-level state machine out of `implement_review`.

`specify` normally creates/selects the SPEC before the cycle begins. If a later phase discovers a real scope/requirements problem, the agent returns to the owner stage and derived artifacts must be revalidated.

See [`docs/FULL_CYCLE.md`](docs/FULL_CYCLE.md).

## Terminal UX and stage handoff

PowerPack-enhanced commands should make the agent workflow observable without inventing host events:

- show planned model routing before material work;
- preserve the host's real reads/searches/writes/shell output/diffs;
- narrate material phase/subtask transitions compactly;
- use one human decision at a time when domain authority is required;
- repeat the planned routing rows at completion with observed result/timing fields;
- use `N/D` rather than estimating unavailable timing;
- end with an explicit semantic handoff such as `ADVANCE`, `RETURN`, `LOOP`, `COMPLETE`, `BLOCKED` or `BLOCKED_BUDGET`.

The model-routing table explains *why* each route exists; timings are wall-clock observations, not token/billing/provider-compute measurements.

## Technical-debt governance

The skill performs context-sensitive deferral judgment; `.specify/powerpack/bin/debt.py` independently enforces deterministic ledger rules and lifecycle mutations.

```mermaid
flowchart LR
    C[Candidate] --> P[PowerPack floor + project policy]
    P -->|current obligation / review / converge / blocker| N[NOT_DEBT]
    P -->|legitimate deferral| O[OPEN]
    O --> I[IN_PROGRESS]
    I --> E[objective resolution evidence]
    E --> R[RESOLVED]
```

Default storage is `docs/technical-debt.md`, with stable IDs, provenance, readiness and evidence-preserving lifecycle. Existing projects may point to their own backlog/policy through `.specify/powerpack/technical-debt.json` without weakening the PowerPack floor.

See [`docs/TECHNICAL_DEBT.md`](docs/TECHNICAL_DEBT.md).

## Mandatory ChatGPT Project Web gate

The second Web gate is part of the default completion contract. A Codex-only approval is insufficient for `COMPLETE`.

PowerPack deliberately uses a **separate persistent Chromium user-data directory** rather than attaching to the default Chrome/Edge profile. This keeps cookies, localStorage and history isolated from normal browsing while allowing the PowerPack login to persist between reviews.

Authorize once per platform/profile/Project binding:

```bash
speckit-powerpack review authorize \
  --profile work \
  --project my-project \
  --url 'https://chatgpt.com/g/g-p-.../project' \
  --path .
```

The browser consent page states the profile path and requested Project URL before any binding is persisted. Cancelling the consent page records no authorization. Legacy `auth login`/`project bind` commands do not satisfy `doctor` by themselves; readiness requires the `playwright-consent` grant.

WSL uses the Linux namespace. Do not point PowerPack at the Windows Edge/Chrome `User Data` directory.

Credentials/MFA are never stored in project configuration. Browser session state remains in the PowerPack profile directory outside the repository.

## Updates and recovery

Check only:

```bash
speckit-powerpack update . --check
```

A normal update requires confirmation, updates the installed CLI from its resolved Git source/ref and then rematerializes PowerPack-managed project assets while preserving project configuration:

```bash
speckit-powerpack update .
# or after explicit pre-approval
speckit-powerpack update . --yes
```

`init` and `install` also perform an update check by default and ask before applying it. Disable one installer check with `--no-update-check`; non-interactive pre-approval uses `--yes-update`.

Forced recovery is explicit:

```bash
speckit-powerpack update . --force --yes
```

Repair only project materialization:

```bash
speckit-powerpack update . --project-only --force --yes
```

Restore mutable PowerPack project configuration to packaged defaults only after explicit approval:

```bash
speckit-powerpack update . --project-only --force --reset-config --yes
```

Even forced recovery never performs `git reset`, rebase, force-push, deletes project code, deletes technical-debt history or deletes platform Web profiles.

See [`docs/UPDATES.md`](docs/UPDATES.md).

## Session/usage limits

Claude/Codex usage/rate/session limits are classified separately from build/test errors. Safe checkpoints contain only resumable execution context; never passwords, cookies, MFA or raw authentication material.

A temporary Claude Code limit does not require changing the SDD workflow. Set Codex as the active integration and continue from the same project/SPEC state with the Codex routing described above.

## Customization and process documentation

- [`docs/CODEX_FIRST_INSTALL.md`](docs/CODEX_FIRST_INSTALL.md) — existing-project migration with Codex as primary executor.
- [`docs/CUSTOMIZATION.md`](docs/CUSTOMIZATION.md) — skill/config customization boundaries.
- [`docs/PROCESS_ARCHITECTURE.md`](docs/PROCESS_ARCHITECTURE.md) — end-to-end process diagrams and source/runtime mapping.
- [`docs/IMPLEMENT_REVIEW.md`](docs/IMPLEMENT_REVIEW.md) — deep review + convergence evidence contract.
- [`docs/FULL_CYCLE.md`](docs/FULL_CYCLE.md) — full-cycle state machine and customization.
- [`docs/TECHNICAL_DEBT.md`](docs/TECHNICAL_DEBT.md) — debt policy/runtime lifecycle.
- [`docs/UPDATES.md`](docs/UPDATES.md) — updater/recovery process diagram and customization map.
- [`docs/PORTABILITY.md`](docs/PORTABILITY.md) — OS/language/framework/build-tool agnostic design.

## Security / safety boundaries

- Codex independent review uses Sol/xhigh/read-only semantics.
- The Codex Terra parent owns writes; the Sol reviewer does not implement findings.
- Recursive Codex CLI spawning for review is forbidden.
- ChatGPT Web requires explicit Playwright consent and an exact Project binding.
- The PowerPack Chromium profile is separated from default Edge/Chrome browser state and from source repositories.
- Review/full-cycle ephemeral state is gitignored; durable findings/receipts are preserved.
- PowerPack workflows do not authorize merge, GitHub approval, ready-for-review, force-push or destructive reset.
- Technical debt cannot hide current-flow blockers/findings.
- Forced updater recovery is constrained to the PowerPack ownership boundary unless the user explicitly requests `--reset-config`.

## Development and CI

```bash
python -m pip install -e '.[dev]'
pytest -q
python -m build --wheel
```

GitHub Actions runs the Ubuntu/Windows/macOS × Python 3.11/3.13 matrix for non-draft PRs and pushes to `main`. While a PR is draft, the CI workflow is intentionally skipped.

## Draft roadmap

Before a stable release, PowerPack is expected to add catalog/release assets for fully catalog-driven Spec Kit Bundle installation, broader integration adapters, additional generic workflows and further hardening extracted from real projects.

## License

MIT. See [LICENSE](LICENSE).
