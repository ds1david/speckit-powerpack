# Windows browser-context authorization (WSL)

This mode exists for ChatGPT accounts whose normal authentication works in the user's Windows Edge/Chrome context but fails in Playwright's bundled Chromium (for example Google SSO/MFA or provider/browser policy checks).

## Security model

The PowerPack does **not** copy the Windows browser profile, cookies, passwords, OAuth tokens or MFA material into WSL.

Instead:

```text
PowerPack CLI in WSL
  -> user explicitly enables remote debugging in an already-running Windows browser
  -> Windows @playwright/cli attaches by browser channel (msedge/chrome)
  -> Playwright operates the existing browser context in place
  -> the user confirms which ChatGPT account that browser session represents
  -> PowerPack stores only metadata/consent + Project binding
```

The official Playwright CLI supports attaching to a running Chrome/Edge by channel after the browser user enables **Allow remote debugging for this browser instance** at `chrome://inspect/#remote-debugging` (Chrome) or the corresponding Edge inspect page.

This is an explicit privileged consent: while remote debugging is enabled and a PowerPack review is running, Playwright can inspect/control tabs in that browser instance. Disable remote debugging when you do not want that access available.

## Prerequisite

The Windows browser-context backend is invoked from WSL but runs the Playwright CLI on Windows. Windows needs Node.js 20+ and `npx.cmd` available.

From WSL you can pre-check:

```bash
cmd.exe /c node --version
cmd.exe /c npx.cmd --version
```

The PowerPack also performs this check during interactive configuration.

## Recommended interactive setup

Run without account/profile parameters:

```bash
speckit-powerpack review auth configure
```

or:

```bash
speckit-powerpack review auth reconfigure
```

The CLI:

1. lists existing ChatGPT reviewer profiles;
2. asks whether to reconfigure an existing profile or create a new one;
3. if the selected profile already has a valid authorization, asks whether it should be replaced;
4. asks for a local account label;
5. asks for the authentication backend;
6. choose **Windows Edge/Chrome context**;
7. asks Edge vs Chrome;
8. opens the browser remote-debugging settings;
9. asks for explicit permission before attaching;
10. opens ChatGPT in a new tab of the existing browser context;
11. lets the user complete Google/SSO/MFA normally in that browser;
12. validates that the ChatGPT composer is reachable;
13. asks the user to confirm the account identity label;
14. records only the consent/backend/browser/account metadata.

## Example account state

```json
{
  "source": "windows-browser-cdp-consent",
  "backend": "windows-browser-context",
  "account_label": "ds1david-plus",
  "browser_channel": "msedge",
  "remote_debugging_consent": true,
  "session_name": "speckit-powerpack-ds1david"
}
```

No cookie or password material belongs in this record.

## Validate the account/session

```bash
speckit-powerpack review auth list
speckit-powerpack review auth validate ds1david
```

For Windows browser-context accounts, `auth validate` performs a live Playwright attach and checks the ChatGPT session.

## Bind a Project

Discover visible Projects through the same Windows browser/account:

```bash
speckit-powerpack review project discover --profile ds1david
```

Then select one:

```bash
speckit-powerpack review project select --profile ds1david --alias atsel --path .
```

Known URL:

```bash
speckit-powerpack review project add \
  'https://chatgpt.com/g/g-p-.../project' \
  --profile ds1david \
  --alias atsel \
  --path .
```

Invite/shared Project:

```bash
speckit-powerpack review project accept-invite \
  '<chatgpt-invite-or-shared-link>' \
  --profile webflow \
  --alias atsel \
  --path .
```

## Validate repository binding

```bash
jq '.chatgpt_web' .specify/powerpack/review.json
jq '.accounts.linux' ~/.config/speckit-powerpack/config.json
jq '.projects' ~/.config/speckit-powerpack/config.json
```

Expected repository fields for Windows browser-context review include:

```text
chatgpt_web.profile = selected logical account profile
chatgpt_web.account_label = selected ChatGPT reviewer identity
chatgpt_web.account_backend = windows-browser-context
chatgpt_web.browser_channel = msedge | chrome
chatgpt_web.project_alias = selected Project alias
chatgpt_web.project_url = exact Project URL
chatgpt_web.authorization = playwright-account-consent
```

Immediately before `speckit-implement-review`:

```bash
speckit-powerpack doctor --strict-review
```

For the Windows browser backend the strict doctor also requires a **live** browser-session check. Keep the configured Windows browser running and remote debugging enabled for that review run.

## Multiple ChatGPT accounts

Use a different logical profile for each account even when they use the same physical Edge/Chrome browser at different times:

```text
ds1david -> ds1david-plus
webflow  -> webflow-plus
```

Before reconfiguring a profile to a different ChatGPT identity, the PowerPack asks before replacement. Reconfiguration invalidates that profile's old Project bindings until they are re-verified.

## Revocation

PowerPack authorization can be removed without logging the user out of Windows Edge/Chrome:

```bash
speckit-powerpack review auth logout ds1david
```

Then disable **Allow remote debugging for this browser instance** in the browser to remove the automation bridge itself.
