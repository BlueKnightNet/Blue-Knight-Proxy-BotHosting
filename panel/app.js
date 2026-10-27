let statusData = null;
let dirty = false;
let saving = false;
let bridgeDirty = false;
let noticeTimer;
let videoRefreshAt = 0;
const $ = id => document.getElementById(id);
const routeAliases = {overview:'overview', home:'overview', sponsor:'sponsor', links:'links', connection:'links', bridge:'bridge'};

function currentPage() {
  return routeAliases[location.hash.replace(/^#\/?/, '').split('?')[0]] || 'overview';
}

function renderRoute(focus = false) {
  const page = currentPage();
  for (const view of document.querySelectorAll('[data-view]')) {
    const active = view.dataset.view === page;
    view.hidden = !active;
    view.classList.toggle('active', active);
  }
  for (const link of document.querySelectorAll('[data-page]')) {
    const active = link.dataset.page === page;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  const title = {overview:'Overview', sponsor:'Sponsored channel', links:'Connection links', bridge:'Cloudflare bridge'}[page];
  document.title = title + ' | Blue Knight Proxy';
  if (focus && statusData) {
    $(page === 'links' ? 'links-heading' : page + '-heading').focus({preventScroll:true});
    window.scrollTo({top:0, behavior:'instant'});
  }
}

function applyTheme(theme) {
  theme = theme === 'cozy' ? 'cozy' : 'dark';
  document.documentElement.dataset.theme = theme;
  document.body.dataset.theme = theme;
  $('theme-label').textContent = theme === 'cozy' ? 'Cozy' : 'Dark';
  $('theme-icon').textContent = theme === 'cozy' ? '\u2600' : '\u263e';
  $('theme-toggle').setAttribute('aria-label', 'Switch to ' + (theme === 'cozy' ? 'dark' : 'cozy') + ' theme');
  $('hero-image').src = '/panel/assets/' + (theme === 'cozy' ? 'cozybg.jpg' : 'bg.jpg');
  try { localStorage.setItem('blueknight-theme', theme); } catch {}
}

async function api(path, data) {
  const response = await fetch(path, {
    method: data ? 'POST' : 'GET', credentials:'same-origin',
    headers: data ? {'Content-Type':'application/json', 'X-CSRF-Token':statusData?.csrf || ''} : {},
    body: data ? JSON.stringify(data) : undefined
  });
  let result;
  try { result = await response.json(); }
  catch { throw new Error('The server did not respond correctly. Try again shortly.'); }
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/login') showLogin();
    throw new Error(result.error || 'Request failed');
  }
  return result;
}

function showLogin() {
  $('dashboard').hidden = true;
  $('login-view').hidden = false;
  $('setup-view').hidden = true;
  statusData = null;
  $('notice').hidden = true;
}

function notice(message, bad = false) {
  clearTimeout(noticeTimer);
  $('notice').textContent = message;
  $('notice').classList.toggle('bad', bad);
  $('notice').setAttribute('role', bad ? 'alert' : 'status');
  $('notice').hidden = false;
  noticeTimer = setTimeout(() => { $('notice').hidden = true; }, bad ? 8000 : 3000);
}

function duration(seconds) {
  if (seconds < 60) return seconds + 's';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
  return Math.floor(seconds / 3600) + 'h ' + Math.floor(seconds % 3600 / 60) + 'm';
}

function bytes(value) {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
  return value.toLocaleString(undefined, {maximumFractionDigits:index ? 2 : 0}) + ' ' + units[index];
}

async function refreshLatestVideo() {
  if (Date.now() < videoRefreshAt) return;
  videoRefreshAt = Date.now() + 300000;
  try {
    const response = await fetch('/api/latest-video', {credentials:'same-origin'});
    if (!response.ok) return;
    const video = await response.json();
    if (!video.ok || !/^[A-Za-z0-9_-]{11}$/.test(video.videoId)) return;
    $('latest-video-link').href = 'https://www.youtube.com/watch?v=' + video.videoId;
    $('latest-video-title').textContent = video.title || 'Watch on YouTube';
    $('latest-video-label').textContent = video.stale ? 'FROM BLUE KNIGHT' : 'LATEST ON YOUTUBE';
    $('latest-video-action').textContent = 'Watch video ↗';
    const thumbnail = $('latest-video-image');
    thumbnail.onerror = () => { thumbnail.src = '/panel/assets/bg.jpg'; thumbnail.onerror = null; };
    thumbnail.src = 'https://i.ytimg.com/vi/' + video.videoId + '/hqdefault.jpg';
    const published = new Date(video.published);
    $('latest-video-date').textContent = Number.isNaN(published.getTime()) ? '' : published.toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'});
  } catch { /* Keep the channel link usable when YouTube cannot be reached. */ }
}

function renderResources(resource = {}) {
  for (const name of ['cpu', 'memory', 'disk']) {
    const percent = resource[name + '_percent'];
    const available = Number.isFinite(percent);
    const level = available ? Math.max(0, Math.min(100, percent)) : 0;
    $(name + '-value').textContent = available ? percent.toFixed(1) + '%' : '\u2014';
    $(name + '-state').textContent = available ? (percent >= 90 ? 'High' : percent >= 70 ? 'Elevated' : 'Healthy') : 'Unavailable';
    $(name + '-state').dataset.level = available ? (percent >= 90 ? 'high' : percent >= 70 ? 'medium' : 'normal') : 'unknown';
    $(name + '-bar').style.width = level + '%';
    $(name + '-meter').setAttribute('aria-valuenow', String(level));
    $(name + '-meter').setAttribute('aria-valuetext', available ? percent.toFixed(1) + ' percent used' : 'Unavailable');
  }
  $('cpu-detail').textContent = Number.isFinite(resource.cpu_cores) ? 'Of ' + resource.cpu_cores.toLocaleString(undefined, {maximumFractionDigits:2}) + ' allocated vCPU' : 'Container CPU metrics unavailable';
  $('memory-detail').textContent = Number.isFinite(resource.memory_used) ? bytes(resource.memory_used) + (resource.memory_limit ? ' / ' + bytes(resource.memory_limit) : ' used; no container limit reported') : 'Container memory metrics unavailable';
  $('disk-detail').textContent = Number.isFinite(resource.disk_used) ? bytes(resource.disk_used) + ' / ' + bytes(resource.disk_total) + (resource.disk_scope === 'deployment' ? ' deployment storage (estimated)' : ' on data filesystem') : 'Data filesystem metrics unavailable';
}

async function refresh(force = false) {
  const s = await api('/api/status');
  statusData = s;
  $('login-view').hidden = true;
  $('setup-view').hidden = true;
  $('dashboard').hidden = false;
  void refreshLatestVideo();
  $('running').textContent = s.running ? 'Online' : 'Starting';
  $('running').classList.toggle('online', s.running);
  $('engine').textContent = s.engine;
  $('uptime').textContent = duration(s.uptime);
  renderResources(s.resources);
  const usage = s.usage;
  $('connected-users').textContent = usage?.available && usage.users !== null ? usage.users.toLocaleString() : '\u2014';
  $('active-connections').textContent = usage?.available ? usage.connections.toLocaleString() : '\u2014';
  $('total-usage').textContent = usage ? bytes(usage.total_bytes) : '\u2014';
  $('upload-usage').textContent = usage ? bytes(usage.upload_bytes) : '\u2014';
  $('download-usage').textContent = usage ? bytes(usage.download_bytes) : '\u2014';
  $('usage-period').textContent = usage ? 'Since ' + new Date(usage.since * 1000).toLocaleDateString() : 'Saved across restarts';
  $('usage-status').textContent = usage?.available ? 'Updates every 15 seconds. Users are estimated from active IPs; shared networks may count as one. Traffic includes direct and WEB proxy connections.' : 'Live metrics are temporarily unavailable. Saved traffic totals are retained.';

  $('traffic-upload-bar').style.width = usage?.total_bytes ? (usage.upload_bytes / usage.total_bytes * 100) + '%' : '0%';
  const networkReady = s.network_ready !== false && Boolean(s.host);
  $('endpoint').textContent = networkReady ? s.host + ':' + s.port : 'Detecting public address...';
  $('network-note').textContent = networkReady ? 'Public address verified automatically. No PUBLIC_HOST or PUBLIC_PORT entry needed.' : 'Finding and verifying your direct proxy address. This updates automatically.';
  $('copy-link').disabled = !networkReady;
  $('copy-tg-link').disabled = !networkReady;
  $('tls-host').textContent = s.tls_host;
  $('web-link').value = s.web_link;
  $('tg-link').value = s.tg_link;
  $('open-telegram').href = networkReady ? s.tg_link : '#/links';
  $('sponsor-badge').textContent = s.settings.enabled ? 'Configured' : 'Not enabled';
  $('sponsor-badge').classList.toggle('on', s.settings.enabled);
  if (s.bridge) {
    $('railway-origin').value = s.bridge.hosting_origin || s.bridge.railway_origin || '';
    $('worker-name').textContent = s.bridge.worker_name || 'join-blueknight-net-tg-...';
    if (!bridgeDirty || force) {
      $('worker-url').value = s.bridge.worker_url;
      $('public-ip').value = s.bridge.public_ip;
      $('bridge-enabled').checked = s.bridge.enabled;
      bridgeDirty = false;
    }
    $('bridge-badge').textContent = s.bridge.enabled ? 'Enabled' : 'Disabled';
    $('bridge-link').value = s.bridge.tg_link;
    $('open-web-telegram').href = s.bridge.tg_link || '#/bridge';
  }
  if (!dirty || force) {
    $('channel').value = s.settings.channel;
    $('ad-tag').value = s.settings.ad_tag;
    $('enabled').checked = s.settings.enabled;
    dirty = false;
  }
  $('last-updated').textContent = 'Updated ' + new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  if (!s.persistent) notice('Keep persistent deployment storage enabled to preserve settings.', true);
  renderRoute();
}

$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter || $('login-form').querySelector('button');
  button.disabled = true;
  $('login-error').textContent = '';
  try {
    await api('/api/login', {password:$('password').value});
    $('password').value = '';
    $('notice').hidden = true;
    await refresh(true);
  } catch (error) { $('login-error').textContent = error.message; }
  finally { button.disabled = false; }
});

$('sponsor-form').addEventListener('input', () => { dirty = true; });
$('sponsor-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (saving || !statusData) return;
  const payload = {enabled:$('enabled').checked, channel:$('channel').value.trim(), ad_tag:$('ad-tag').value.trim()};
  if (payload.enabled && !/^[a-fA-F0-9]{32}$/.test(payload.ad_tag)) {
    notice('Enter the 32-character promotion tag from @MTProxybot before enabling sponsorship.', true);
    $('ad-tag').focus();
    return;
  }
  const needsRestart = payload.enabled !== statusData.settings.enabled || (payload.enabled && payload.ad_tag.toLowerCase() !== statusData.settings.ad_tag);
  if (needsRestart && !confirm('Applying this change restarts the proxy engine. Clients may briefly reconnect. Continue?')) return;
  saving = true;
  $('save').disabled = true;
  $('save').textContent = 'Applying...';
  try {
    await api('/api/settings', payload);
    dirty = false;
    await refresh();
    notice(payload.enabled ? 'Sponsor configuration saved. Telegram controls channel delivery; allow time for the promotion to update.' : 'Settings saved. Sponsorship is disabled.');
  } catch (error) { notice(error.message, true); }
  finally { saving = false; $('save').disabled = false; $('save').textContent = 'Save changes \u2192'; }
});

$('refresh').addEventListener('click', async () => {
  $('refresh').disabled = true;
  try { await refresh(); } catch (error) { notice(error.message, true); }
  finally { $('refresh').disabled = false; }
});

$('logout').addEventListener('click', async () => {
  try { await api('/api/logout', {}); }
  catch (error) { notice(error.message, true); return; }
  dirty = false;
  $('sponsor-form').reset();
  $('web-link').value = '';
  $('tg-link').value = '';
  $('bridge-token').value = '';
  $('worker-source').value = '';
  $('bridge-link').value = '';
  $('open-web-telegram').href = '#/bridge';
  bridgeDirty = false;
  $('notice').hidden = true;
  showLogin();
});

async function copy(value, label, input) {
  if (!value) { notice('Connection details are not loaded yet. Refresh and try again.', true); return; }
  try {
    await navigator.clipboard.writeText(value);
    notice(label + ' copied.');
  } catch {
    if (input) { const details = input.closest('details'); if (details) details.open = true; input.focus(); input.select(); }
    notice('Automatic copying is unavailable. ' + (input ? 'The link is selected; press Ctrl+C or use your device\'s Copy command.' : 'Copy the key from your deployment logs.'), true);
  }
}

$('copy-link').addEventListener('click', () => copy(statusData?.web_link, 'HTTPS link', $('web-link')));
$('copy-tg-link').addEventListener('click', () => copy(statusData?.tg_link, 'Direct Telegram link', $('tg-link')));
$('copy-key').addEventListener('click', () => copy(statusData?.registration_secret, 'Registration key'));
$('copy-bridge-link').addEventListener('click', () => copy(statusData?.bridge?.tg_link, 'Telegram WEB link', $('bridge-link')));
for (const id of ['web-link', 'tg-link', 'bridge-link']) $(id).addEventListener('click', () => $(id).select());
$('bridge-form').addEventListener('input', () => { bridgeDirty = true; });
$('worker-url').addEventListener('input', () => { $('public-ip').value = ''; });
$('bridge-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (saving) return;
  saving = true;
  $('save-bridge').disabled = true;
  try {
    await api('/api/bridge/settings', {worker_url:$('worker-url').value.trim(), enabled:$('bridge-enabled').checked, public_ip:$('public-ip').value.trim()});
    bridgeDirty = false;
    await refresh();
    notice('WEB settings saved. Use the WEB link in a compatible Telegram client after deploying the Worker.');
  } catch (error) { notice(error.message, true); }
  finally { saving = false; $('save-bridge').disabled = false; }
});
async function loadWorkerCode(reveal = false) {
  const response = await fetch('/api/bridge/standalone', {credentials:'same-origin'});
  if (!response.ok) throw new Error('Could not load Worker code. Sign in again and retry.');
  const source = await response.text();
  $('worker-source').value = source;
  $('worker-source-box').open = reveal;
  return source;
}
$('copy-worker-code').addEventListener('click', async () => {
  try { await copy(await loadWorkerCode(), 'Ready-to-deploy Worker code', $('worker-source')); }
  catch (error) { notice(error.message, true); }
});
$('load-worker-code').addEventListener('click', () => loadWorkerCode(true).catch(error => notice(error.message, true)));
$('copy-bridge-token').addEventListener('click', async () => {
  try {
    const result = await api('/api/bridge/token');
    $('bridge-token').value = result.token;
    await copy(result.token, 'Private bridge token', $('bridge-token'));
  } catch (error) { notice(error.message, true); }
});
$('theme-toggle').addEventListener('click', () => applyTheme(document.body.dataset.theme === 'cozy' ? 'dark' : 'cozy'));
window.addEventListener('hashchange', () => renderRoute(true));
let initialTheme = 'dark';
try { initialTheme = localStorage.getItem('blueknight-theme') || 'dark'; } catch {}
applyTheme(initialTheme);
renderRoute();
async function initialize() {
  try {
    const setup = await api('/api/setup/status');
    if (setup.required) {
      $('login-view').hidden = true;
      $('dashboard').hidden = true;
      $('setup-view').hidden = false;
      return;
    }
    await refresh();
  } catch { showLogin(); }
}
$('setup-form').addEventListener('submit', async event => {
  event.preventDefault();
  const password = $('setup-password').value;
  if (password !== $('setup-confirm').value) { $('setup-error').textContent = 'Passwords do not match.'; return; }
  const button = $('setup-form').querySelector('button');
  button.disabled = true;
  $('setup-error').textContent = '';
  try {
    await api('/api/setup', {code:$('setup-code').value.trim(), password});
    $('setup-form').reset();
    await api('/api/login', {password});
    await refresh(true);
  } catch (error) { $('setup-error').textContent = error.message; }
  finally { button.disabled = false; }
});
initialize();
setInterval(() => { if (statusData && !saving) refresh().catch(error => notice(error.message, true)); }, 15000);
