Blue Knight standalone Telegram WEB bridge

PHONE / BROWSER SETUP (no terminal)
1. Create a Cloudflare Hello World Worker, then open Edit code.
2. Paste ALL of worker-standalone.mjs and deploy.
3. Settings > Variables and Secrets:
   RAILWAY_ORIGIN = your Railway HTTPS origin (Text)
   BRIDGE_TOKEN = Copy bridge token from your own panel (Secret)
4. Save and deploy changes.
5. Save the workers.dev URL in your panel. Leave Endpoint public IPv4 empty,
   enable WEB proxy, and save. Use a compatible Telegram client.

The standalone file has no imports or runtime packages. Your phone is enough.
Each deployment owner uses their own Railway origin and private token.

OPTIONAL DESKTOP SETUP
Run inside the extracted folder on your PC:
  npx --yes wrangler@4 login
  npx --yes wrangler@4 deploy
  node upload-secret.mjs
Your Railway origin is in wrangler.jsonc -> vars -> RAILWAY_ORIGIN.
These commands are not needed for browser deployment.

Keep bridge-config.json and BRIDGE_TOKEN private. Do not publish this ZIP.
People connecting need only a Telegram client supporting WEB proxies.
Original FakeTLS links remain available separately. Cloudflare/network limits apply.
