# Browser Reviewer Identities

PowerPack treats the browser carrying the ChatGPT session as part of the Web-review identity.

## Core rule

```text
logical PowerPack profile
  + ChatGPT account
  + selected desktop browser/session
  + ChatGPT Project binding
  = one Web reviewer identity
```

There is **no automatic fallback** between browsers/accounts/backends.

An interactive setup may offer `try another browser/account`, but only after an explicit user decision. A failed attempt stores no grant. The new browser is authenticated and validated from the beginning.

## Multiple accounts

A user can intentionally keep different ChatGPT accounts in different browsers:

```text
ds1david-edge
  account_label = ds1david-plus
  browser       = Edge

webflow-chrome
  account_label = webflow-plus
  browser       = Chrome
```

Both profiles may be bound to the same shared ChatGPT Project. The repository selects exactly one reviewer identity at a time.

Example:

```bash
speckit-powerpack review auth configure
speckit-powerpack review auth configure

speckit-powerpack review auth list

speckit-powerpack review project select --profile ds1david-edge --alias atsel --path .
speckit-powerpack review project select --profile webflow-chrome --alias atsel --path .
```

Select the account/browser that will perform Web review:

```bash
speckit-powerpack review project use atsel --profile ds1david-edge --path .
```

or:

```bash
speckit-powerpack review project use atsel --profile webflow-chrome --path .
```

Validate the active repository binding:

```bash
jq '.chatgpt_web | {
  profile,
  account_label,
  account_backend,
  host_scope,
  automation_browser_id,
  project_alias,
  project_url,
  authorization
}' .specify/powerpack/review.json

speckit-powerpack doctor --strict-review
```

## Environment detection

PowerPack detects the runtime/browser host:

- WSL -> Windows browser host;
- native Linux -> Linux desktop (GNOME/KDE/etc.) and Wayland/X11 when available;
- macOS -> native macOS browser host.

The interactive setup lists detected browsers and marks their automation capability.

On Windows/WSL it also probes Windows App Paths so Edge/Chrome can be found even when their executables are not on `PATH`.

## Login and automation use the same browser

For a reviewer profile, the selected browser is opened first **without Playwright control** so normal Google/SSO/MFA can complete.

After login:

1. the user explicitly grants remote-debugging/automation permission;
2. Playwright attaches to that same browser instance/session;
3. PowerPack validates the authenticated ChatGPT UI;
4. the user confirms the account label;
5. only then is the authorization persisted.

PowerPack does not export cookies, OAuth tokens, passwords, MFA material or browser-profile data.

## Explicit browser/account retry

If login or attach fails:

```text
failure
  -> no grant stored
  -> [T] try another browser/account OR [C] cancel
```

Choosing `T` is an explicit reviewer-identity change, not fallback. Nothing switches silently.

## Firefox

Firefox may be detected because it can be a real user login browser. However, an already-running branded Firefox session does not have the same attach path used by Chromium/CDP.

Therefore PowerPack must not mark an existing Firefox session as automated-review capable unless a real supported existing-session backend is implemented and validated.

Today Firefox is shown as `manual-only`; it does not satisfy the mandatory automated ChatGPT Web gate.

## Review-time rule

Once `speckit-implement-review` starts, the configured reviewer identity is immutable for that run unless the run blocks for configuration and the user explicitly reconfigures/rebinds it.

A review failure never causes PowerPack to silently use another browser/account or downgrade to Codex-only completion.
