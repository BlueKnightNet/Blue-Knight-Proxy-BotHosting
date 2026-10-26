import fs from 'node:fs';
import { spawnSync } from 'node:child_process';

const config = JSON.parse(fs.readFileSync('bridge-config.json', 'utf8'));
if (!/^[A-Za-z0-9_-]{32,128}$/.test(config.token || '')) throw new Error('Invalid token in bridge-config.json');
// Only fixed arguments enter the Windows command shell. Token travels on stdin.
const result = spawnSync(process.platform === 'win32' ? 'npx.cmd' : 'npx',
  ['--yes', 'wrangler@4', 'secret', 'put', 'BRIDGE_TOKEN'],
  {input:config.token + '\n', stdio:['pipe','inherit','inherit'], shell:process.platform === 'win32'});
process.exitCode = result.status ?? 1;
