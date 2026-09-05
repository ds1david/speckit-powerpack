# SpecKit PowerPack

> **Status: Draft / pre-release.** The repository is intentionally evolving before its first stable public release.

SpecKit PowerPack is a composable enhancement layer for the official [GitHub Spec Kit](https://github.com/github/spec-kit). It does **not** fork or replace Spec Kit. It uses Spec Kit-native presets/extensions and adds reusable workflow state, convergence, deep implementation review, full-cycle orchestration, technical-debt governance, capability-driven portability and managed updates.

## What this draft adds

- `speckit-checklist-converge` with same-SPEC predecessor enforcement.
- `speckit-implement` wrapper with precise before/after workspace delta receipts.
- `speckit-converge` integration with PowerPack state.
- one canonical `speckit-implement-review` with ATSEL-derived deep-review hardening.
- Deep Review Evidence Protocol: immutable snapshot identity, requirements/baseline coverage, previous-finding validation, full-snapshot re-review and adversarial verdict challenge.
- review schema 2.0 validator with `BLOCKED_REVIEW_CONTRACT` and `BLOCKED_REPEATED_FINDING`.
- durable review findings in `tasks.md`: `PENDING → SELECTED → IMPLEMENTED → RESOLVED`.
- `speckit-full-cycle` with a resumable same-SPEC state machine for implement/converge/review loops.
- governed technical-debt lifecycle: `speckit-debt-create`, `list`, `consult`, `start`, `close` plus a deterministic project-local ledger runtime.
- debt safety floor forbidding active SPEC work, convergence gaps, review findings and blockers from becoming deferred debt.
- architecture/OS/language/framework/build-tool agnostic capability resolution.
- Claude Code / Codex executor-aware reviewer routing without recursive Codex spawning.
- optional ChatGPT Project Web second gate with platform-scoped browser profiles and project bindings.
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

    PRE --> IMP[speckit-implement]
    PRE --> CONV[speckit-converge]
    PRE --> REV[speckit-implement-review]
    PRE --> FULL[speckit-full-cycle]
    PRE --> DEBT[technical-debt lifecycle]

    EXT --> DOC[doctor]
    EXT --> UPD[confirmed update/recovery]

    CLI --> RT[Project-local Python runtimes]
    RT --> STATE[same-SPEC receipts/review ledger]
    RT --> CAP[capability resolver]
    RT --> RP[review protocol validator]
    RT --> FC[full-cycle state machine]
    RT --> TD[technical-debt ledger]
```

Generated `.claude/skills/*` and `.agents/skills/*` files are materialized views, not the durable customization source.

## Requirements

- Python 3.11+
- Git
- `uv` when PowerPack must bootstrap Spec Kit or self-update
- Claude Code and/or Codex CLI
- Playwright only for the optional ChatGPT Project Web gate

Current reviewer route:

| Executor | Independent reviewer | Recursive Codex spawn |
|---|---|---|
| Claude Code | exactly one external `codex exec` | forbidden |
| Codex | current Codex session | forbidden |
| unknown/other | `BLOCKED` | not attempted |

Deep Codex reviewer profile: `gpt-5.6-sol / xhigh / read-only`.

## Installation

`uv tool install` accepts a Git source directly as the package argument. During development, install this PR branch with:

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@feat/speckit-implement-review-convergence-clean
```

After the implementation is on `main`:

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@main
```

Initialize a project:

```bash
mkdir my-project
cd my-project
speckit-powerpack init . --integration claude
```

or:

```bash
speckit-powerpack init . --integration codex
```

Existing Spec Kit project:

```bash
speckit-powerpack install . --integration claude
```

If `specify` is missing:

```bash
speckit-powerpack install . --integration claude --bootstrap-speckit
```

PowerPack bootstraps the official Spec Kit Git source through `uv tool install git+https://github.com/github/spec-kit.git@<tested-tag>`.

Diagnose:

```bash
speckit-powerpack doctor
```

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

## Same-SPEC workflow safety

PowerPack does not treat artifact existence as proof that a predecessor actually ran.

```mermaid
flowchart LR
    C[speckit-checklist / SPEC-A] --> CR[receipt SPEC-A]
    CR --> CC[speckit-checklist-converge / SPEC-A]
    CR -. invalid .-> CCB[checklist-converge / SPEC-B]

    I[speckit-implement / SPEC-A] --> IR[receipt SPEC-A]
    IR --> R[speckit-implement-review / SPEC-A]
    IR -. invalid .-> RB[implement-review / SPEC-B]
```

The implement wrapper also snapshots workspace content. A file already dirty before the round is not attributed to the round unless its contents change again.

## Capability-driven quality gates

No universal Maven/Gradle/npm/pytest command is embedded in workflow skills. The installed `capabilities.py` discovers a reproducible strategy and fails closed on unknown/ambiguous architecture. Documentation-only implementation deltas are `NOT_APPLICABLE`.

Project override lives in `.specify/powerpack/quality-gates.json`:

```json
{
  "schema_version": 1,
  "policy": "capability-strategy",
  "custom_command": ["make", "verify"],
  "unknown_architecture": "block",
  "ambiguous_architecture": "block"
}
```

See [`docs/PORTABILITY.md`](docs/PORTABILITY.md).

## Canonical `speckit-implement-review`

There is exactly one canonical asset: `speckit.implement-review.md`. The earlier `speckit.implement-review-v2.md` was only a migration artifact and has been removed.

```mermaid
flowchart TD
    SNAP[Bind SPEC/base/merge-base/head/digest] --> PREV[Validate previous findings]
    PREV --> FULL[Review full current snapshot]
    FULL --> ADV[Adversarial verdict challenge]
    ADV --> JSON[Schema 2.0 evidence JSON]
    JSON --> VAL[review_protocol.py]
    VAL -->|invalid| BC[BLOCKED_REVIEW_CONTRACT]
    VAL -->|findings| TASKS[Persist REV-* in tasks.md]
    TASKS --> FIX[Implement selected/all batch]
    FIX --> GATE[capability-selected gate]
    GATE --> VAL2[resolve with evidence]
    VAL2 --> SNAP
    VAL -->|approved| WEB{Web second gate configured?}
    WEB -->|no| DONE[review converged]
    WEB -->|yes| W[ChatGPT Project same HEAD]
    W --> VAL
```

Findings can never be converted to debt/backlog/TODO merely to force convergence.

See [`docs/IMPLEMENT_REVIEW.md`](docs/IMPLEMENT_REVIEW.md).

## `speckit-full-cycle`

The workflow composes existing commands and stores an authoritative current phase per SPEC:

```text
clarify → plan → checklist/checklist-converge → tasks → analyze
→ implement ↔ converge
→ implement-review ↔ implementation fixes
→ DONE
```

The runtime remembers whether a correction implementation must return to `converge` or `implement_review`, enforces configured round limits and supports resume/abort without deleting SPEC/review evidence.

Configure `.specify/powerpack/full-cycle.json`. The invariants `same_spec_only=true`, `stop_on_blocked=true` and `allow_debt_escape_hatch=false` cannot be weakened.

See [`docs/FULL_CYCLE.md`](docs/FULL_CYCLE.md).

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

## ChatGPT Project Web gate

Persistent browser identities are platform-scoped:

```text
<global PowerPack config>/browser-profiles/
├── windows/work/
├── linux/work/     # WSL uses Linux namespace
└── macos/work/
```

The same project alias may bind to different profile/account/project URLs per platform.

```bash
speckit-powerpack review auth login work
speckit-powerpack review project bind my-project 'https://chatgpt.com/g/g-p-.../project' --profile work
speckit-powerpack review project use my-project
speckit-powerpack review project list --all-platforms
```

Credentials/MFA are entered only in the real browser.

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

## Customization and process documentation

- [`docs/CUSTOMIZATION.md`](docs/CUSTOMIZATION.md) — skill/config customization boundaries.
- [`docs/PROCESS_ARCHITECTURE.md`](docs/PROCESS_ARCHITECTURE.md) — end-to-end process diagrams and source/runtime mapping.
- [`docs/IMPLEMENT_REVIEW.md`](docs/IMPLEMENT_REVIEW.md) — deep review evidence contract.
- [`docs/FULL_CYCLE.md`](docs/FULL_CYCLE.md) — full-cycle state machine and customization.
- [`docs/TECHNICAL_DEBT.md`](docs/TECHNICAL_DEBT.md) — debt policy/runtime lifecycle.
- [`docs/UPDATES.md`](docs/UPDATES.md) — updater/recovery process diagram and customization map.
- [`docs/PORTABILITY.md`](docs/PORTABILITY.md) — OS/language/framework/build-tool agnostic design.

## Security / safety boundaries

- Codex independent review uses read-only sandbox semantics.
- Browser auth lives outside source repositories and is separated by platform.
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

GitHub Actions runs the Ubuntu/Windows/macOS × Python 3.11/3.13 matrix for non-draft PRs and pushes to `main`. While a PR is draft, the CI workflow is intentionally `skipped`.

## Draft roadmap

Before a stable release, PowerPack is expected to add catalog/release assets for fully catalog-driven Spec Kit Bundle installation, broader integration adapters, additional generic workflows and further hardening extracted from real projects.

## License

MIT. See [LICENSE](LICENSE).
