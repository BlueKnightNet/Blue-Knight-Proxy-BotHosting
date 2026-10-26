# Blue Knight Proxy - Bot-Hosting

A Telegram MTProto proxy with a private owner panel, sponsored-channel settings
and an optional Cloudflare WEB bridge. Built for Bot-Hosting's Python runtime.

**[Step-by-step setup guide](docs/SETUP.md)** | **[Standalone Cloudflare Worker](bridge/worker-standalone.mjs)** | **[Join BlueKnight Net](https://t.me/BlueKnight_Net)**

## Features

- Native FakeTLS MTProto and the HTTPS owner panel share one allocated port.
- First-visit password setup: the owner chooses an 8+ character password using
  a one-time verification code from hosting deployment logs. No preset password.
- Editable sponsored-channel settings for every deployment owner.
- Phone-only Cloudflare setup: paste one Worker file into the browser editor.
- Connected-user estimates, active connections and persistent traffic totals.
- Container CPU/memory and estimated deployment storage usage.
- Persistent settings, secrets and owner password hash in `.data/`.
- BlueKnight-branded Worker names and a channel link in the panel.

No Railway account, Docker, root permissions or pip packages are needed.
The standalone Worker requires no Node.js or Wrangler commands.

## Quick deployment - no manual networking variables

1. Fork this repository and create a Bot-Hosting deployment from your fork.
2. Select **Python** and branch **main**. The default entry file is already
   **main.py**. If choosing a custom startup command, use `python3 -u main.py`.
3. Enable the deployment's HTTPS domain and start it.
4. Open `/panel/`, enter the one-time setup code from hosting deployment logs,
   and choose your own password (8+ characters).
5. Open Connection links and copy your verified Telegram link.

**Do not enter PUBLIC_HOST, PUBLIC_PORT or PANEL_PUBLIC_ORIGIN for normal setup.**
The app reads the allocated port, detects the public IPv4, verifies that it reaches
this exact deployment, and learns your HTTPS panel URL after owner sign-in.
An HTTPS `.apps.bot-hosting.cloud` alias is never used as a native TCP hostname.
If detection is still running, the panel waits instead of sharing a broken link.

The first boot downloads pinned Telemt 3.5.14 and verifies the archive checksum.
State is saved in `.data/` on the deployment's persistent storage. Do not delete
it when updating. No hosting-account API key is needed in the app.

## Cloudflare bridge - copy and paste from your phone

1. In your panel open Cloudflare bridge and tap **Copy ready-to-deploy Worker**.
2. In your Cloudflare account create a Worker, open Edit code, replace all example
   code with the copied code and deploy.
3. Copy the resulting workers.dev URL into your panel. Leave endpoint IPv4 empty,
   enable WEB proxy and save.

**No Cloudflare variables, manual token entry, Node.js or Wrangler commands are
needed for this flow.** The private copied code already contains your panel URL
and bridge token. Do not publish that copied file or show its private token in a
recording. Each owner's panel generates its own configuration.

The repository's [standalone template](bridge/worker-standalone.mjs) is generic
and has no secrets. It is an advanced alternative requiring UPSTREAM_ORIGIN (Text)
and BRIDGE_TOKEN (Secret) in Cloudflare settings. Use the panel's copy button for
the automatic flow. A private desktop/Wrangler bundle remains optional.

Hosting-account creation, enabling the host's HTTPS domain, choosing your password,
Cloudflare account approval and Telegram promotion registration require the owner.
The application does not bypass those ownership steps.

## Sponsored channels

Every deployment owner chooses their own sponsor channel. Register the native
proxy address and port with [@MTProxybot](https://t.me/MTProxybot), use **Copy
registration key** when it asks for the 32-hex secret, and associate your channel
through **Set promotion**. Save the bot's promotion tag in the panel.

The hostname branding does not replace bot registration or automatically
subscribe users. Telegram controls promotion delivery. A working WEB connection
alone does not prove the sponsored channel is displayed by a WEB client.

## Storage and free-plan limits

Keep `.data/` private and backed up. It contains your proxy key, bridge token,
owner password hash, sponsor settings and cumulative usage totals. Never publish
the private Worker ZIP, deployment API keys or `.env` files.

Bot-Hosting currently provides a free pool of 256 MB RAM, 25% CPU, 512 MB storage,
one deployment and one port, with **manual renewal every four days**. Check
[current plans](https://bot-hosting.net/pricing) before deploying. This is not
unlimited bandwidth or a guarantee of availability on every network.

`PANEL_STORAGE_LIMIT_MB` defaults to 512; update it if your allocation differs.
Connected users are estimates from active IPs, not Telegram account identities.

## Development

Python 3.11+ and a current Node.js release are sufficient for the tests:

```sh
python scripts/test-panel.py
python scripts/test-port-router.py
python scripts/test-network.py
node --test scripts/test-bridge.mjs
```

The deployed app itself needs only Python and the downloaded Telemt engine.

## Project layout

- `main.py`: verified engine download, startup and process supervision.
- `hosting/port_router.py`: bounded HTTP/FakeTLS routing on one public port.
- `hosting/network.py`: verified public-address detection and owner-origin setup.
- `panel/`: owner UI, authenticated API and private engine supervision.
- `bridge/`: standalone Worker, optional desktop bundle and instructions.
- `docs/SETUP.md`: complete setup and troubleshooting guide.
- `scripts/`: validation tests.

UI asset attribution is preserved in [panel/NOTICE.md](panel/NOTICE.md).
The proxy engine is [Telemt](https://github.com/telemt/telemt).
