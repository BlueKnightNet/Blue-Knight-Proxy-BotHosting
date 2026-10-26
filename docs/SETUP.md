# Blue Knight Proxy: Bot-Hosting setup

This repository supports Bot-Hosting's Python runtime. Use `bothosting.py` as the
entry file. You do not need Docker, root access, pip packages or a separate disk
volume. State is stored in `.data/` on the deployment's persistent storage.

## Create the deployment

1. In Bot-Hosting create a deployment from your public GitHub fork.
2. Select the **Python** runtime, version **3.12**, and branch **main** (or your chosen branch).
3. Set **Entry file** to `bothosting.py`. If using a custom startup command, use
   `python3 -u bothosting.py` from the deployment root.
4. Stay within your free resource pool. No paid package is required by the code.
5. Enable the deployment's public HTTPS subdomain. A branded alias such as
   `join-blueknight-net-tg-<id>` is optional.

## Set deployment environment variables

| Variable | Value |
| --- | --- |
| `PANEL_PUBLIC_ORIGIN` | Your complete HTTPS panel origin, e.g. `https://my-app.apps.bot-hosting.cloud` |
| `PUBLIC_HOST` | Your deployment's node hostname from Networking, e.g. `fi16.bot-hosting.cloud` |
| `PUBLIC_PORT` | Its allocated public port, also exposed by `SERVER_PORT` |
| `PANEL_STORAGE_LIMIT_MB` | Optional; defaults to the free plan's 512. Change if your deployment has another storage allocation. |

The examples are not addresses to copy blindly: use your own deployment's values.
Do not set `SERVER_PORT` yourself; the host allocates it. The application reads
it automatically. If `PUBLIC_PORT` is omitted it defaults to `SERVER_PORT`.

Optional: keep an existing `SECRET` to preserve your proxy key. Keep an existing
`PANEL_PASSWORD_HASH` or set `PANEL_PASSWORD` (8+ characters) if you want to skip
browser setup. Password variables should be marked secret in the host panel.

## Start and sign in

Start the deployment. First boot downloads pinned Telemt 3.5.14 from its official
release and verifies the archive checksum. The executable is cached in `.cache/`.

Open `https://YOUR-APP/health`, which should return `ok`, then `/panel/`.
For a new owner:
1. Open the deployment Console/Logs in your Bot-Hosting dashboard.
2. Find the line beginning `[setup] Open /panel/ and enter this one-time setup code:`.
3. Open your panel HTTPS domain and paste that code into First-time setup.
4. Choose a password of at least 8 characters, confirm it and submit.

The code verifies that you control the hosting account. It cannot reset a password
once setup is complete. The chosen password is stored as a salted, iterated hash.
No preset password is included. Optional password variables take precedence;
leave them unset when you want browser setup.

The free plan publishes one port. The included bounded TCP router distinguishes
ordinary HTTP from FakeTLS and forwards each to the correct internal listener.
Your panel HTTPS address and native Telegram TCP link therefore share one
allocation. Native clients' IP addresses are passed to the loopback engine using
PROXY protocol. Metrics/control ports are private.

## Cloudflare WEB bridge

1. Create a Cloudflare account at https://dash.cloudflare.com/sign-up, verify your
   email and open Workers & Pages. No purchased domain is required.
2. In your panel open **Cloudflare bridge** and copy the standalone Worker code.
3. In Cloudflare create a Hello World Worker using the branded name from the
   panel. Open Edit code, replace the entire example with the copied code and deploy.
4. In Worker settings > Variables and Secrets set `UPSTREAM_ORIGIN` (Text) to **Your hosting origin** from
   the panel, and `BRIDGE_TOKEN` (Secret) using **Copy bridge token**.
5. Save the workers.dev URL in your panel, leave public IPv4 empty, enable WEB
   proxy and save. Use a compatible Telegram client.

Use `UPSTREAM_ORIGIN` for this deployment. No other hosting account or Wrangler
commands are needed. Each owner uses their own HTTPS origin and private token.

## Sponsorship

The Sponsored channel tab remains editable. Register the new node hostname/IP
and allocated public port with @MTProxybot, send the panel's 32-hex registration
key when asked, and associate the channel through Set promotion. Enter the bot's
promotion tag in the panel. Registration for an old server is not automatically
migrated to a new server.

## Persistence and free-plan limits

Keep `.data/` intact: it contains your owner hash, proxy secret, sponsor settings,
bridge token and usage totals. Do not use a reinstall/wipe operation without a
backup. Keep the hosting API key out of the repository and the Worker.

Bot-Hosting currently requires free deployments to be **renewed manually every
four days**. Its free pool currently provides 256 MB RAM, 25% CPU, 512 MB storage,
one deployment and one port. This is limited hosting, not unlimited throughput.
The adapter uses Telemt even when sponsorship is disabled to avoid downloading
and running an additional proxy engine.

The Bot-Hosting disk card estimates this deployment's file sizes against the
configured storage allocation, rather than displaying the shared node's disk.

References: [Python hosting](https://bot-hosting.net/python-hosting),
[API and networking](https://bot-hosting.net/api),
[current plans and renewal rules](https://bot-hosting.net/pricing).

## Updating an existing deployment

Use the host's GitHub sync operation with this repository and branch `main`.
Keep the Python runtime, entry file and environment variables. Do not reinstall,
wipe the deployment files, or delete `.data/`. Native and Worker links stay valid
when their hostnames, ports and saved secrets stay the same.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| App unreachable | Python 3.12, entry bothosting.py, allocated SERVER_PORT, deployment logs. |
| Setup screen asks for a code | Read the one-time code from your own deployment logs. |
| Unexpected existing password | Remove optional PANEL_PASSWORD/PANEL_PASSWORD_HASH overrides only if you intend to use browser setup; existing owner.json still preserves a configured password. |
| Native link has wrong server | Set PUBLIC_HOST to the assigned node hostname and PUBLIC_PORT to its allocated port. |
| Worker Not configured | Set UPSTREAM_ORIGIN (Text) and BRIDGE_TOKEN (Secret). |
| Worker Bridge unavailable | Check the panel /health URL, enabled WEB proxy and the Worker's origin. |
| Wrong endpoint IPv4 | Clear the field and save; it must resolve the Worker hostname, not the hosting node. |
| Bot rejects registration secret | Copy registration key supplies exactly 32 hex characters. |
| Sponsored channel absent | Check bot registration, Set promotion, promotion tag and propagation time. |
| Disk limit changed | Set PANEL_STORAGE_LIMIT_MB to your actual allocation. |
| Settings lost | Preserve .data and restore your backup instead of creating new secrets. |
