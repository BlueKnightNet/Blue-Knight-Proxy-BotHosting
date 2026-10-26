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

## Quick deployment

1. Fork this repository and create a Bot-Hosting deployment from your fork.
2. Select **Python 3.12**, branch **main**, and entry file **bothosting.py**.
3. If setting a custom startup command, use `python3 -u bothosting.py`.
4. Enable the hosting HTTPS domain and add these variables using your own values:

   | Variable | Value |
   | --- | --- |
   | `PANEL_PUBLIC_ORIGIN` | Your complete HTTPS panel origin, without a path |
   | `PUBLIC_HOST` | Your allocated node hostname from Networking |
   | `PUBLIC_PORT` | Your allocated public port; otherwise uses SERVER_PORT |

5. Start the deployment. Open `/health`, then `/panel/`.
6. Copy the one-time setup code from deployment logs and choose your password
   in the browser. Keep `.data/` intact across updates.

The first boot downloads pinned Telemt 3.5.14 and verifies the archive checksum.
Later boots reuse the cached engine. You do not need to attach a separate `/data`
volume: this host's deployment storage contains `.data/` and `.cache/`.

## Cloudflare bridge from a phone

In **Cloudflare bridge**, use **Copy standalone Worker code**. Create a Worker
in Cloudflare's browser editor, replace its example code and deploy. Add:

| Variable | Cloudflare type | Value |
| --- | --- | --- |
| `UPSTREAM_ORIGIN` | Text | Your hosting origin shown in the panel |
| `BRIDGE_TOKEN` | Secret | Copy bridge token from your own panel |

Save/deploy changes. Paste the workers.dev URL into your panel, leave Endpoint
public IPv4 empty for automatic resolution, enable WEB proxy and save.
Connecting users need a Telegram client that supports WEB proxies.

The source file is [bridge/worker-standalone.mjs](bridge/worker-standalone.mjs).
It has no imports or external packages. A private desktop/Wrangler bundle is
also available as an optional deployment method.

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
node --test scripts/test-bridge.mjs
```

The deployed app itself needs only Python and the downloaded Telemt engine.

## Project layout

- `bothosting.py`: verified engine download, startup and process supervision.
- `hosting/port_router.py`: bounded HTTP/FakeTLS routing on one public port.
- `panel/`: owner UI, authenticated API and private engine supervision.
- `bridge/`: standalone Worker, optional desktop bundle and instructions.
- `docs/SETUP.md`: complete setup and troubleshooting guide.
- `scripts/`: validation tests.

UI asset attribution is preserved in [panel/NOTICE.md](panel/NOTICE.md).
The proxy engine is [Telemt](https://github.com/telemt/telemt).
