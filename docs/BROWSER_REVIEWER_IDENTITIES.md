# Reviewer Identities

PowerPack treats one dedicated ChatGPT-Web2API service and its persistent Chrome profile as one Web-review account identity.

## Core rule

```text
logical PowerPack profile
  + ChatGPT account authenticated in dedicated Chrome profile
  + reviewer REST endpoint
  + ChatGPT Project binding
  = one Web reviewer identity
```

There is **no automatic fallback** between accounts, endpoints or Projects.

## Multiple Plus accounts

Use one service/profile/port pair per account:

```text
ds1david
  account_label = ds1david-plus
  endpoint      = http://127.0.0.1:8080
  Chrome profile = PowerPack/ds1david

webflow
  account_label = webflow-plus
  endpoint      = http://127.0.0.1:8081
  Chrome profile = PowerPack/webflow
```

Both may be bound to the same shared ChatGPT Project. The repository selects exactly one reviewer profile at a time.

Example:

```bash
speckit-powerpack review service start --profile ds1david --port 8080 --cdp-port 9222
speckit-powerpack review auth configure

speckit-powerpack review service start --profile webflow --port 8081 --cdp-port 9223
speckit-powerpack review auth configure

speckit-powerpack review auth list
speckit-powerpack review project select --profile ds1david --alias atsel --path .
speckit-powerpack review project select --profile webflow --alias atsel --path .
```

Switch explicitly:

```bash
speckit-powerpack review project use atsel --profile ds1david --path .
# or
speckit-powerpack review project use atsel --profile webflow --path .
```

Validate:

```bash
speckit-powerpack review binding show --path . --json
speckit-powerpack doctor --strict-review
```

## WSL and native desktops

When PowerPack runs in WSL, `review service start` starts ChatGPT-Web2API on the Windows host so the service, CDP endpoint and dedicated Chrome all share the same OS/loopback namespace. PowerPack invokes the reviewer REST endpoint through Windows loopback; it does not need a WSL port proxy.

On native Linux/macOS/Windows, the service is started in the local host environment.

## Authentication

The service launches a real headed Chrome with a dedicated persistent profile. Complete Google/SSO/MFA directly in that browser once. The browser may stay minimized during reviews.

PowerPack does not copy cookies, OAuth tokens, passwords or MFA material from personal Edge/Chrome/Firefox profiles. Reviewer state is separate from the Git worktree.

## Explicit account change

If a reviewer endpoint/account fails:

```text
failure
  -> current Web gate blocks
  -> no automatic endpoint/account switch
  -> user explicitly reconfigures/rebinds another reviewer if desired
```

This is an identity change, not fallback.

## Review-time rule

Once `speckit-implement-review` starts, the configured reviewer identity is immutable for that run unless it blocks for configuration and the user explicitly reconfigures/rebinds it.

A review failure never causes PowerPack to silently use another account/endpoint or downgrade to Codex-only completion.
