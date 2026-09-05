# ChatGPT Web accounts, profiles and Project bindings

The PowerPack models Web review with two separate concepts:

```text
Playwright profile = authenticated ChatGPT account identity
Project binding    = Project context selected for one repository
```

This separation is intentional. Authentication is **not** granted to one Project. After a ChatGPT account is authorized in its isolated PowerPack browser profile, any Project accessible to that account can be discovered, selected, opened from a known URL, or joined through an invite/shared link.

## Isolation from Windows browsers

PowerPack never reuses the default Edge/Chrome profile. In WSL/Linux, profiles live under:

```text
~/.config/speckit-powerpack/browser-profiles/linux/<profile>/
```

Examples:

```text
browser-profiles/linux/ds1david/
browser-profiles/linux/webflow/
```

Those two directories have independent cookies, local storage, ChatGPT sessions and account identity. They are also independent from Windows browser data.

## Authorize one ChatGPT account

```bash
speckit-powerpack review auth authorize ds1david \
  --account-label ds1david-plus
```

The visible Playwright Chromium window first shows a PowerPack consent page and then opens ChatGPT. Credentials/MFA are entered only on ChatGPT. The resulting grant is account-scoped:

```text
source = playwright-account-consent
profile = ds1david
account_label = ds1david-plus
```

It is not tied to a Project yet.

A second subscription/account gets another isolated profile:

```bash
speckit-powerpack review auth authorize webflow \
  --account-label webflow-plus
```

List accounts:

```bash
speckit-powerpack review auth list
```

Select the default account for subsequent Project commands:

```bash
speckit-powerpack review auth use ds1david
```

Changing the active account does not silently change an already configured repository reviewer. Use `project use/select/add` to change the actual repository binding.

## Reconfigure authentication

Reuse the existing isolated profile and re-authorize:

```bash
speckit-powerpack review auth reconfigure ds1david \
  --account-label ds1david-plus
```

Start with a fresh PowerPack browser session for only that profile:

```bash
speckit-powerpack review auth reconfigure ds1david \
  --account-label ds1david-plus \
  --fresh
```

Reauthorization deliberately marks previous Project bindings for that profile as stale. This prevents a profile name from being silently repointed to another ChatGPT account while old Project authorization remains trusted. Re-select or re-add the Project afterwards.

Forget one profile and its bindings:

```bash
speckit-powerpack review auth forget webflow --path .
```

## Discover Projects visible to an account

```bash
speckit-powerpack review project discover --profile ds1david
```

PowerPack opens ChatGPT using exactly that profile. Expand/load the Projects sidebar and return to the terminal. PowerPack scans the loaded Project links and prints a numbered list.

Select from the discovered list and bind the chosen Project to the current repository:

```bash
speckit-powerpack review project select \
  --profile ds1david \
  --path .
```

For deterministic/non-interactive selection after discovery:

```bash
speckit-powerpack review project select \
  --profile ds1david \
  --index 2 \
  --alias atsel \
  --path .
```

If the Project is not present in the currently loaded sidebar, choose it manually in ChatGPT:

```bash
speckit-powerpack review project select \
  --profile ds1david \
  --manual \
  --alias atsel \
  --path .
```

The browser remains authoritative for Project access. PowerPack only persists a binding after the selected page resolves to a ChatGPT Project URL ending in `/project`.

## Bind a known Project URL

```bash
speckit-powerpack review project add \
  'https://chatgpt.com/g/g-p-.../project' \
  --profile ds1david \
  --alias atsel \
  --path .
```

The URL is opened in the selected profile so access is verified before binding.

## Accept an invite/shared Project link

```bash
speckit-powerpack review project accept-invite \
  '<chatgpt-invite-or-shared-link>' \
  --profile webflow \
  --alias atsel \
  --path .
```

The invite/shared link opens in the `webflow` profile. Accept/join the Project in the browser if needed, navigate to the resulting Project, then return to the terminal. PowerPack persists only the final Project URL.

ChatGPT supports shared Projects for Free, Go, Plus and Pro users. A Project owner may invite users directly or, when configured for link access, allow logged-in users with the link to join. Opening/interacting with a shared Project URL can also make it appear in the collaborator's sidebar.

## One Project, multiple reviewer accounts

A single local alias can have multiple bindings on the same platform:

```text
atsel
└── linux
    ├── ds1david
    │   ├── account = ds1david-plus
    │   └── url = https://chatgpt.com/g/g-p-.../project
    └── webflow
        ├── account = webflow-plus
        └── url = https://chatgpt.com/g/g-p-.../project
```

For example, register the owner account first:

```bash
speckit-powerpack review project add \
  'https://chatgpt.com/g/g-p-.../project' \
  --profile ds1david \
  --alias atsel \
  --path .
```

Then register the collaborator account through its invite/shared access:

```bash
speckit-powerpack review project accept-invite \
  '<shared-link>' \
  --profile webflow \
  --alias atsel \
  --path .
```

Choose which authenticated account performs Web review:

```bash
speckit-powerpack review project use atsel \
  --profile ds1david \
  --path .
```

or:

```bash
speckit-powerpack review project use atsel \
  --profile webflow \
  --path .
```

That selection writes the effective identity into `.specify/powerpack/review.json`:

```json
{
  "chatgpt_web": {
    "required": true,
    "enabled": true,
    "project_alias": "atsel",
    "project_url": "https://chatgpt.com/g/g-p-.../project",
    "profile": "webflow",
    "account_label": "webflow-plus",
    "authorization": "playwright-account-consent"
  }
}
```

The selected profile/account is authoritative. PowerPack must not silently substitute another authenticated account merely because that account can also access the same Project.

## Doctor behavior

Use the normal doctor to diagnose installation plus onboarding:

```bash
speckit-powerpack doctor
```

Missing account/Project onboarding is reported as `SETUP`, not as a broken installation. The command still fails for real installation defects such as an incompatible Spec Kit, missing runtime assets or unavailable selected executor.

Before `speckit-implement-review`, use the strict readiness gate:

```bash
speckit-powerpack doctor --strict-review
```

Strict review readiness requires:

```text
OK web-review-required
OK playwright-package
OK playwright-browser
OK chatgpt-account-authenticated
OK chatgpt-project-bound
```

A stale binding after account reauthorization does not satisfy this gate.

## Security boundaries

- Credentials/MFA are entered only on ChatGPT.
- Browser session state is outside the Git repository.
- PowerPack profiles never point to the default Windows Edge/Chrome profile.
- Each account gets a distinct persistent profile directory.
- Reauthentication invalidates old Project trust for that profile.
- Project bindings store profile/label/URL metadata, not passwords or raw cookies.
