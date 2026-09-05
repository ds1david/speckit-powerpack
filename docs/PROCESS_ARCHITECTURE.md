# PowerPack Process Architecture

This is the canonical map from PowerPack process nodes to their implementation, installed project artifact, durable/ephemeral state and supported customization surface.

The reusable design rule is:

```text
project intent / stricter policy
        ↓
PowerPack workflow contract
        ↓
capability / state / evidence runtime
        ↓
Spec Kit primitive / reviewer / external gate
        ↓
auditable result
```

OS, language, framework, IDE and build-tool differences must be resolved behind capabilities/configuration rather than embedded as branches in workflow skills.

# 1. Package → project → machine layers

```mermaid
flowchart LR
    subgraph PKG[Installable speckit-powerpack package]
        PRESET[powerpack-core preset]
        EXT[powerpack-tools extension]
        CFG[default config assets]
        RT[Python runtime assets]
        POL[policies / protocols / templates]
        CLI[CLI + update_manager.py]
    end

    subgraph PROJECT[One initialized project]
        CMD[Spec Kit materialized commands]
        PCFG[.specify/powerpack/*.json]
        BIN[.specify/powerpack/bin/*.py]
        PDOC[installed policies / protocols / template]
        SPEC[specs/... artifacts + tasks.md]
        PSTATE[durable state receipts]
        RSTATE[gitignored execution state]
    end

    subgraph MACHINE[Machine/platform-local state]
        GCFG[PowerPack global config.json]
        AUTH[browser-profiles/platform/profile]
        TOOL[uv-managed CLI]
    end

    PRESET --> CMD
    EXT --> CMD
    CFG --> PCFG
    RT --> BIN
    POL --> PDOC
    CLI --> TOOL
    CMD --> SPEC
    BIN --> PSTATE
    BIN --> RSTATE
    GCFG --> AUTH
```

**Durable customization source:** package source, project `.specify/powerpack` configuration/policies and project-local skills/gates.

**Not a durable customization source:** generated `.claude/skills/*`, `.agents/skills/*` or other materialized agent copies.

# 2. End-to-end feature process

```mermaid
flowchart TD
    U[User / agent request] --> ONE[Resolve or create exactly one SPEC]
    ONE --> FC[full_cycle.py start]
    FC --> C[clarify]
    C --> P[plan]
    P --> CK{Checklist applicable?}
    CK -->|yes| K[checklist]
    K --> KC[checklist-converge]
    CK -->|no| SKIP[Runtime records checklist + checklist-converge skipped]
    KC --> T[tasks]
    SKIP --> T
    T --> A[analyze]
    A -->|contradiction| BF[BLOCKED / repair specification artifacts]
    BF --> A
    A -->|consistent| I[implement]

    I --> IB[powerpack.py implement begin]
    IB --> CORE[Official Spec Kit implement]
    CORE --> IE[powerpack.py implement end]
    IE --> DELTA[Precise same-SPEC implementation delta/receipt]

    DELTA --> V[converge]
    V --> VG{Remaining specified work?}
    VG -->|yes| VR[full_cycle: needs-implementation]
    VR --> I
    VG -->|no| R[implement-review]

    R --> RG{Valid findings?}
    RG -->|yes| L[Persist every finding in tasks.md]
    L --> I2[Implement selected/all review batch]
    I2 --> G[Capability-selected quality gate]
    G -->|fail/block| I2
    G -->|pass or N/A| RR[Resolve finding evidence]
    RR --> R
    RG -->|no; approved| W{Web gate configured?}
    W -->|no| DONE[full_cycle DONE]
    W -->|yes| WEB[ChatGPT Project deep review same HEAD]
    WEB -->|findings| L
    WEB -->|approved| DONE
```

The `full_cycle.py` state is authoritative for which phase may execute next. A blocked state requires explicit resume/unblock before another `advance` call.

# 3. Full-cycle state machine

```mermaid
stateDiagram-v2
    [*] --> Clarify
    Clarify --> Plan
    Plan --> Checklist
    Checklist --> ChecklistConverge: applicable
    Checklist --> Tasks: NOT_APPLICABLE (both checklist phases skipped)
    ChecklistConverge --> Tasks
    Tasks --> Analyze
    Analyze --> Implement
    Implement --> Converge
    Converge --> Implement: needs implementation
    Converge --> ImplementReview: converged
    ImplementReview --> Implement: findings
    ImplementReview --> Done: approved current snapshot
    Clarify --> Blocked: blocker
    Plan --> Blocked: blocker
    Analyze --> Blocked: blocker
    Converge --> Blocked: round limit / blocker
    ImplementReview --> Blocked: round limit / blocker
    Blocked --> Clarify: resume --unblock when clarify was current
    Blocked --> Plan: resume --unblock when plan was current
    Blocked --> Analyze: resume --unblock when analyze was current
    Blocked --> Converge: resume --unblock when converge was current
    Blocked --> ImplementReview: resume --unblock when review was current
```

State stores `return_after_implement`, so a correction implementation deterministically returns to either `converge` or `implement_review`.

## Full-cycle file map

| Concern | Package source | Installed/project location | Customization |
|---|---|---|---|
| workflow prompt | `assets/presets/powerpack-core/commands/speckit.full-cycle.md` | materialized by Spec Kit | package change only for generic orchestration semantics |
| default phases/limits | `assets/config/default-full-cycle.json` | `.specify/powerpack/full-cycle.json` | mode, optional phases, round limits |
| state machine | `assets/runtime/powerpack_full_cycle.py` | `.specify/powerpack/bin/full_cycle.py` | package-level reusable state semantics only |
| execution state | runtime-created | `.specify/powerpack/runtime/full-cycle/<spec>.json` | do not hand-edit; use start/status/advance/resume/abort |

Non-weakenable config: `same_spec_only=true`, `stop_on_blocked=true`, `allow_debt_escape_hatch=false`.

# 4. Implementation and capability gate

```mermaid
flowchart TD
    B[Implement begin] --> S1[Snapshot tracked + untracked content hashes]
    S1 --> SI[Official implementation]
    SI --> S2[Snapshot after]
    S2 --> D[Changed files attributable to this run]
    D --> DOC{Docs/non-executable only?}
    DOC -->|yes| NA[NOT_APPLICABLE]
    DOC -->|no| CAP[capabilities.py discovery]
    CAP -->|one reproducible strategy| RUN[Execute strategy]
    CAP -->|unknown / ambiguous / missing executable| BLOCK[BLOCKED_CONFIGURATION]
```

| Concern | Package source | Installed location | Customization |
|---|---|---|---|
| receipts/delta | `assets/runtime/powerpack_runtime.py` | `.specify/powerpack/bin/powerpack.py` | generic package semantics only |
| capability strategies | `assets/runtime/powerpack_capabilities.py` | `.specify/powerpack/bin/capabilities.py` | add reusable architecture strategies here |
| project gate override | generated by `cli.py` | `.specify/powerpack/quality-gates.json` | explicit argv `custom_command` |

A project-specific traceability/closure script belongs to the project; PowerPack only needs a generic contract for invoking it when/if a reusable closure-gate mechanism is configured.

# 5. Deep implementation review

```mermaid
sequenceDiagram
    participant I as Implementer/orchestrator
    participant P as powerpack.py
    participant R as Independent reviewer
    participant V as review_protocol.py
    participant T as same-SPEC tasks.md
    participant C as capabilities.py
    participant W as ChatGPT Web optional

    I->>P: prereq check implement-review
    P-->>I: same-SPEC implement receipt
    I->>P: review route/start
    P-->>I: executor route + current HEAD
    I->>R: immutable snapshot + deep-review protocol
    R-->>I: schema 2.0 evidence JSON
    I->>V: validate (+ previous JSON after first round)
    alt invalid evidence contract
        V-->>I: BLOCKED_REVIEW_CONTRACT / BLOCKED_REPEATED_FINDING
    else findings
        V-->>I: valid CHANGES_REQUIRED
        I->>P: ingest
        P->>T: durable REV-* PENDING
        I->>P: select batch
        I->>I: implement selected/all
        I->>C: gate detect/run
        C-->>I: pass / N-A / block
        I->>P: resolve with evidence
        P->>T: RESOLVED
        I->>R: fresh full-snapshot review new HEAD
    else approved
        alt Web disabled
            V-->>I: converged
        else Web enabled
            I->>W: same HEAD + same protocol
            W-->>I: evidence JSON
            I->>V: validate Web result
        end
    end
```

## Review file map

| Concern | Package source | Installed/project location | Customization |
|---|---|---|---|
| canonical skill | `assets/presets/powerpack-core/commands/speckit.implement-review.md` | materialized command | generic workflow only |
| runtime routing/findings | `assets/runtime/powerpack_runtime.py` | `.specify/powerpack/bin/powerpack.py` | package state semantics |
| evidence validator | `assets/runtime/powerpack_review_protocol.py` | `.specify/powerpack/bin/review_protocol.py` | schema evolution at package level |
| methodology | `assets/review/deep-review-protocol.md` | `.specify/powerpack/deep-review-protocol.md` | project may add stricter domain probes |
| review config | `assets/config/default-review.json` | `.specify/powerpack/review.json` | modes/Web selection/profile settings |
| model routing | `assets/config/default-model-routing.json` | `.specify/powerpack/model-routing.json` | stage model mappings; reviewer contract stays independent |

# 6. Platform-scoped ChatGPT Web identity

```mermaid
flowchart TD
    OS{Current platform} -->|Windows| WP[browser-profiles/windows/profile]
    OS -->|Linux / WSL| LP[browser-profiles/linux/profile]
    OS -->|macOS| MP[browser-profiles/macos/profile]
    WP --> WB[alias binding: windows]
    LP --> LB[alias binding: linux]
    MP --> MB[alias binding: macos]
    WB --> USE[review project use]
    LB --> USE
    MB --> USE
    USE --> RJ[project review.json selects current-platform binding]
    RJ --> WEB[ChatGPT Project Web gate]
```

Implementation is `src/speckit_powerpack/cli.py`. Persistent identity lives outside the repository under the platform-native PowerPack config root. Projects select bindings through CLI commands; they should not copy raw browser profile directories between OSes.

# 7. Technical-debt governance and lifecycle

```mermaid
flowchart TD
    C[Potential deferred work] --> FLOOR[Load PowerPack debt safety floor]
    FLOOR --> PP[Load stricter project policy paths]
    PP --> SEM{Semantic creation gate}
    SEM -->|active SPEC / review / converge / blocker| ND[NOT_DEBT]
    SEM -->|legitimately deferrable| RT[debt.py create]
    RT --> MG{Mechanical guards}
    MG -->|P0 / active obligation / forbidden origin| ND
    MG -->|duplicate| DUP[DUPLICATE]
    MG -->|valid| OPEN[OPEN + stable ID + lifecycle]
    OPEN --> READY{Readiness READY?}
    READY -->|no| HOLD[OPEN + BLOCKED/NEEDS_REFINEMENT]
    READY -->|yes| START[debt.py start]
    START --> PROG[IN_PROGRESS]
    PROG --> WORK[Normal Spec Kit implementation workflow]
    WORK --> PROOF{Original resolution criteria objectively proven?}
    PROOF -->|no| PROG
    PROOF -->|yes| CLOSE[debt.py close --criteria-satisfied --evidence]
    CLOSE --> RES[RESOLVED + preserved history]
```

## Debt file map

| Concern | Package source | Installed/project location | Customization |
|---|---|---|---|
| debt skills | `assets/presets/powerpack-core/commands/speckit.debt-*.md` | materialized commands | project policy provides domain semantics |
| deterministic ledger | `assets/runtime/powerpack_debt.py` | `.specify/powerpack/bin/debt.py` | generic storage/lifecycle behavior |
| floor policy | `assets/policies/technical-debt.md` | `.specify/powerpack/technical-debt-policy.md` | project may only become stricter |
| config | `assets/config/default-technical-debt.json` | `.specify/powerpack/technical-debt.json` | backlog path, prefix, project policies |
| default backlog shape | `assets/templates/technical-debt-backlog.md` | `.specify/powerpack/technical-debt-template.md` | project may bind an established deterministic format/adapter |
| actual default ledger | created by debt runtime | `docs/technical-debt.md` | version-controlled project backlog |

# 8. Install, update and forced recovery

```mermaid
flowchart TD
    START[init / install / agent update] --> UC[Load update.json]
    UC --> META[Read installed PEP 610 VCS metadata]
    META --> REF[Resolve Git repository + ref]
    REF --> REM[git ls-remote]
    REM --> CMP{Compare installed commit}
    CMP -->|same| CURRENT[CURRENT]
    CMP -->|different| AVAILABLE[UPDATE_AVAILABLE]
    CMP -->|cannot prove installed source| UNKNOWN[UNKNOWN_INSTALLED_SOURCE]
    REM -->|error| CF[CHECK_FAILED]

    AVAILABLE --> ASK{Explicit confirmation?}
    ASK -->|no| KEEP[Keep current install]
    ASK -->|yes| SELF[uv tool install --force git+repo@ref]
    UNKNOWN -->|normal| STOP[Stop]
    CF -->|normal| STOP
    UNKNOWN -->|explicit --force --yes| SELF
    CF -->|explicit --force --yes| SELF
    CURRENT -->|explicit --force --yes| SELF

    SELF --> REFRESH{Initialized project + refresh enabled?}
    REFRESH -->|yes| NEWCLI[Invoke NEW CLI project-only force refresh]
    REFRESH -->|no| DONE[CLI updated]
    NEWCLI --> CFGRESET{Explicit --reset-config?}
    CFGRESET -->|no| PRESERVE[Overwrite managed assets; preserve project config]
    CFGRESET -->|yes + force + yes| RESET[Restore mutable PowerPack config defaults]
    PRESERVE --> SAFE[Preserve source, debt history, Web auth and Git history]
    RESET --> SAFE
```

## Update file map

| Concern | Package source | Installed/project location | Customization |
|---|---|---|---|
| update policy | `assets/config/default-update.json` | `.specify/powerpack/update.json` | channel/ref/check/refresh policy |
| installed source/ref resolver | `src/speckit_powerpack/update_manager.py` | installed CLI package | package-level updater semantics |
| install/update orchestration | `src/speckit_powerpack/cli.py` | `speckit-powerpack` executable | CLI flags/config |
| agent-facing update skill | `assets/extensions/powerpack-tools/commands/update.md` | materialized extension command | project may add stricter approval policy |
| managed project refresh | `cli.py::install_support/install_components` | `.specify/powerpack` + Spec Kit components | configs preserved by default |

`--force` is brute-force only inside the PowerPack ownership boundary. `--reset-config` is a separate stronger action and requires explicit `--force --yes`. No updater path authorizes Git reset/rebase/force-push or deletion of project source/debt/browser profiles.

# 9. Session-limit resume

```mermaid
flowchart LR
    LIMIT[Claude/Codex usage or rate limit] --> CLASS[powerpack.py limit classify]
    CLASS --> CP[Persist safe limit checkpoint]
    CP --> STOP[Stop/wait/resume later]
    STOP --> STATUS[full_cycle/review status]
    STATUS --> RESUME[Resume exact phase / review state]
```

Limit checkpoints contain safe execution context, never passwords, cookies, MFA or raw browser authentication.

# 10. Change decision guide

```mermaid
flowchart TD
    N[Need new behavior] --> U{Reusable across unrelated projects?}
    U -->|no| LOCAL[Project-local skill / policy / closure gate]
    U -->|yes| K{Behavior type}
    K -->|workflow ordering/state| WF[PowerPack command + state runtime]
    K -->|config/default| CFG[PowerPack config asset]
    K -->|OS/language/framework/build support| CAP[Capability strategy]
    K -->|review methodology/evidence| REV[Review protocol/validator]
    K -->|debt lifecycle/storage| DEBT[Debt policy/runtime]
    K -->|installation/update/recovery| UPDATE[CLI/update_manager]
```

Examples that stay project-local: WASAPI lifecycle, WSL-first policy, trading-specific invariants, Oracle APEX metadata rules, a specific backend-to-frontend route traceability implementation.

Examples that belong in PowerPack: same-SPEC receipts, generic convergence/review lifecycle, evidence contracts, capability resolution, technical-debt governance mechanics, full-cycle orchestration, platform-scoped Web identity and safe updater/recovery behavior.

See also [`CUSTOMIZATION.md`](CUSTOMIZATION.md), [`IMPLEMENT_REVIEW.md`](IMPLEMENT_REVIEW.md), [`FULL_CYCLE.md`](FULL_CYCLE.md), [`TECHNICAL_DEBT.md`](TECHNICAL_DEBT.md), [`UPDATES.md`](UPDATES.md) and [`PORTABILITY.md`](PORTABILITY.md).
