# Blue Knight Proxy: Bot-Hosting setup

This repository supports Bot-Hosting's Python runtime. Use `main.py` as the
entry file. You do not need Docker, root access, pip packages or a separate disk
volume. State is stored in `.data/` on the deployment's persistent storage.

## Create the deployment

1. In Bot-Hosting create a deployment from your public GitHub fork.
2. Select the **Python** runtime, version **3.12**, and branch **main** (or your chosen branch).
3. Set **Entry file** to `main.py`. If using a custom startup command, use
   `python3 -u main.py` from the deployment root.
4. Stay within your free resource pool. No paid package is required by the code.
5. Enable the deployment's public HTTPS subdomain. A branded alias such as
   `join-blueknight-net-tg-<id>` is optional.

## Networking is automatic

Leave PUBLIC_HOST, PUBLIC_PORT and PANEL_PUBLIC_ORIGIN unset for normal deployment.
The application reads SERVER_PORT from the host. If SERVER_IP is not a usable
public address, it discovers the node's public IPv4 and checks a per-process
identity response through the allocated port before publishing a link.

Open your HTTPS panel URL to set up the owner password. Once ownership is verified,
the app records that URL automatically for Worker generation. No account API key
is required. Wrong `.apps` aliases in PUBLIC_HOST are ignored rather than put into
native Telegram links.

For advanced environments only, PUBLIC_HOST can supply a real node hostname;
it must still pass verification. PANEL_PUBLIC_ORIGIN can override HTTPS origin
detection for a custom domain. PANEL_STORAGE_LIMIT_MB defaults to 512 on the free
plan and can be adjusted for another storage allocation.

Leave PANEL_PASSWORD and PANEL_PASSWORD_HASH unset to choose your password in the
browser. Existing owner password files are preserved across updates.

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

## Cloudflare WEB bridge: automatic configuration

1. Create a Cloudflare account, verify your email and open Workers & Pages.
2. In your own panel open **Cloudflare bridge > Copy ready-to-deploy Worker**.
3. Create a Hello World Worker using the branded name shown in your panel.
4. Open Edit code, replace all example code with the copied code, and deploy.
5. Paste its HTTPS workers.dev URL into your panel, leave Endpoint public IPv4
   empty, enable WEB proxy and save.
6. Use Open WEB proxy in Telegram with a client supporting WEB proxies.

The copied code already contains your hosting URL and bridge token. No variables,
secret-pasting, PC, terminal or Wrangler are needed. Keep that private copied code
out of GitHub and hide it during recordings. The public template in the repository
has no credentials and is intended for advanced manual configuration.

The owner must still approve deployment in their own Cloudflare account. The app
cannot create an account or approve a platform login on someone else's behalf.

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
| App unreachable | Python 3.12, entry main.py, allocated SERVER_PORT, deployment logs. |
| Setup screen asks for a code | Read the one-time code from your own deployment logs. |
| Unexpected existing password | Remove optional PANEL_PASSWORD/PANEL_PASSWORD_HASH overrides only if you intend to use browser setup; existing owner.json still preserves a configured password. |
| Native link has wrong server | Wait for automatic address verification; check deployment logs for network detection retries. |
| Worker Not configured | Use Copy ready-to-deploy Worker from your own panel, then replace the entire Worker code and deploy. |
| Worker Bridge unavailable | Check /health, enable WEB proxy, and copy fresh ready-to-deploy code from this panel. |
| Wrong endpoint IPv4 | Clear the field and save; it must resolve the Worker hostname, not the hosting node. |
| Bot rejects registration secret | Copy registration key supplies exactly 32 hex characters. |
| Sponsored channel absent | Check bot registration, Set promotion, promotion tag and propagation time. |
| Disk limit changed | Set PANEL_STORAGE_LIMIT_MB to your actual allocation. |
| Settings lost | Preserve .data and restore your backup instead of creating new secrets. |

## Latest on YouTube card

Works automatically on deployment. No API key, Google account, or additional
configuration is required. The default channel is Blue Knight Net.

The server reads YouTube's public channel feed for the latest listed video title,
thumbnail and publication date. Thumbnails are served through the panel and tied
to the displayed video ID. The premium card and single-line adaptive titles work
on desktop and mobile. Views and likes are hidden in this default mode because
the feed does not reliably provide those statistics.

Optional environment variables (normally leave unset):
- `YOUTUBE_CHANNEL_ID`: another channel ID. Default: `UCOUsLDQyNHhp_g7-jeZAJyg`.
- `YOUTUBE_CACHE_SECONDS`: default `600` (10 minutes); minimum 300, maximum 86400.
- `YOUTUBE_API_KEY`: optional secret for owners who want official view/like counts
  and stricter public-video/premiere validation using YouTube Data API v3. Enable
  that API in Google Cloud before configuring a key. Never put the key in GitHub
  or the Worker. This is not required for the normal card.

Restart after changing optional variables. The last successful metadata snapshot
is saved to `.data/youtube-cache.json`. Temporary failures keep that snapshot with
a stale-data label. An open panel refreshes automatically; requests are cached
and shared across visitors. No fabricated counts or dates are shown.

The public feed contains recent uploads and can be delayed; it does not expose
all video availability or scheduled-premiere status fields. The optional API mode
scans the uploads playlist, validates public availability and excludes upcoming
broadcasts. New uploads and removals are reflected on the next successful fetch,
subject to YouTube's feed/API update timing. API mode uses one channels request
plus one playlistItems and one videos request per nonempty uploads page per refresh.
