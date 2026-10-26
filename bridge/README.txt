Blue Knight WEB bridge - phone setup

AUTOMATIC FLOW (recommended)
1. Open your own panel > Cloudflare bridge > Copy ready-to-deploy Worker.
2. In Cloudflare's browser editor paste it over the example Worker and deploy.
3. Paste the workers.dev URL back into your panel, enable WEB proxy and save.
No variables, token entry, PC or Wrangler commands are needed.
The copied file contains a private token: do not publish it or expose it in videos.

ADVANCED / GENERIC TEMPLATE
worker-standalone.mjs in this ZIP is generic. To deploy that file directly, set
UPSTREAM_ORIGIN (Text) to your panel HTTPS URL and BRIDGE_TOKEN (Secret) from
bridge-config.json. Or use the panel copy button for the already-configured code.

OPTIONAL DESKTOP FLOW
Inside this extracted folder run:
  npx --yes wrangler@4 login
  npx --yes wrangler@4 deploy
  node upload-secret.mjs

Keep bridge-config.json and this private ZIP out of public repositories.
Telegram users need a client that supports WEB proxies. Hosting/network limits apply.
