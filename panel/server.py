"""Private management panel for the Bot-Hosting Telemt deployment."""
import base64
import hashlib
import hmac
import http.cookies
import http.client
import ipaddress
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
BRIDGE_ROOT = ROOT.parent / "bridge"


class Resources:
    """Linux container counters, normalized to its CPU and memory allocation."""
    def __init__(self, directory, cgroup=Path("/sys/fs/cgroup")):
        self.directory = directory
        self.cgroup = Path(cgroup)
        self.previous = None
        self.cached = {}
        self.sampled = 0
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            if now - self.sampled < 2:
                return self.cached
            result = {"cpu_percent": None, "cpu_cores": None, "memory_used": None, "memory_limit": None,
                      "memory_percent": None, "disk_used": None, "disk_total": None, "disk_percent": None, "disk_scope": "filesystem"}
            try:
                cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
                quota, period = (self.cgroup / "cpu.max").read_text().split()
                if quota != "max":
                    cores = min(cores, int(quota) / int(period))
                cpu = dict(line.split() for line in (self.cgroup / "cpu.stat").read_text().splitlines())
                used = int(cpu["usage_usec"]) / 1000000
                if self.previous and now > self.previous[0] and used >= self.previous[1]:
                    result["cpu_percent"] = min(100, max(0, (used - self.previous[1]) / (now - self.previous[0]) / cores * 100))
                result["cpu_cores"] = cores
                self.previous = (now, used)
            except (OSError, ValueError, KeyError, ZeroDivisionError):
                pass
            try:
                result["memory_used"] = int((self.cgroup / "memory.current").read_text())
                limit = (self.cgroup / "memory.max").read_text().strip()
                if limit != "max":
                    result["memory_limit"] = int(limit)
                    result["memory_percent"] = min(100, result["memory_used"] / result["memory_limit"] * 100)
            except (OSError, ValueError, ZeroDivisionError):
                pass
            try:
                if os.environ.get("PANEL_STORAGE_ROOT") and os.environ.get("PANEL_STORAGE_LIMIT_MB"):
                    root = Path(os.environ["PANEL_STORAGE_ROOT"])
                    used = sum((Path(folder) / name).lstat().st_size for folder, _, names in os.walk(root) for name in names)
                    total = int(os.environ["PANEL_STORAGE_LIMIT_MB"]) * 1024 * 1024
                    result.update(disk_used=used, disk_total=total, disk_percent=min(100, used / total * 100), disk_scope="deployment")
                else:
                    disk = shutil.disk_usage(self.directory)
                    result.update(disk_used=disk.used, disk_total=disk.total, disk_percent=disk.used / disk.total * 100)
            except (OSError, ValueError, ZeroDivisionError):
                pass
            self.cached, self.sampled = result, now
            return result


def parse_usage_metrics(text):
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r'([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^\n]*\})?\s+([0-9.eE+\-]+)(?:\s+\d+)?', line)
        if match:
            value = float(match[3])
            if value >= 0 and value < 2 ** 64:
                values[(match[1], match[2] or "")] = int(value)
    def total(name, label=None):
        return sum(v for (n, labels), v in values.items() if n == name and (label is None or label in labels))
    required = "telemt_user_connections_current"
    return {"connections": total(required), "users": total("telemt_user_unique_ips_current"),
            "upload": total("telemt_user_octets_from_client_total"), "download": total("telemt_user_octets_to_client_total"),
            "valid": "# HELP telemt_user_connections_current " in text}

def validate_bridge(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid bridge settings")
    url = str(data.get("worker_url", "")).strip().rstrip("/")
    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("Invalid bridge state")
    if url:
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path or parsed.port not in (None, 443)
                    or not re.fullmatch(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+", parsed.hostname or "")):
                raise ValueError()
        except ValueError:
            raise ValueError("Enter an HTTPS Worker origin, without a path, query or credentials")
        url = "https://" + parsed.hostname.lower()
    public_ip = str(data.get("public_ip", "")).strip()
    if public_ip:
        address = ipaddress.ip_address(public_ip)
        if address.version != 4 or not address.is_global:
            raise ValueError("Public endpoint must be a public IPv4 address")
    if enabled and not url:
        raise ValueError("Enter the deployed Worker URL first")
    return {"worker_url": url, "enabled": enabled, "public_ip": public_ip}


def write_private_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data))
    temp.chmod(0o600)
    os.replace(temp, path)


def panel_password_hash():
    digest = os.environ.get("PANEL_PASSWORD_HASH", "").strip()
    if digest:
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("PANEL_PASSWORD_HASH must be a SHA-256 hex digest")
        return digest
    password = os.environ.get("PANEL_PASSWORD", "")
    if len(password) < 8:
        raise ValueError("Set PANEL_PASSWORD to a unique password of at least 8 characters, or set PANEL_PASSWORD_HASH")
    return hashlib.sha256(password.encode()).hexdigest()


def bridge_bundle(proxy):
    status = proxy.status()
    state = proxy.bridge
    config = {"name": proxy.worker_name(), "main": "worker.mjs", "compatibility_date": "2026-10-01", "workers_dev": True,
              "vars": {"UPSTREAM_ORIGIN": proxy.hosting_origin()}}
    helper = {"worker_url": state["worker_url"] or "https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev",
              "token": state["token"]}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("worker.mjs", "worker-core.mjs", "worker-standalone.mjs", "upload-secret.mjs", "README.txt"):
            archive.writestr(name, (BRIDGE_ROOT / name).read_bytes())
        archive.writestr("wrangler.jsonc", json.dumps(config, indent=2))
        archive.writestr("bridge-config.json", json.dumps(helper, indent=2))
        archive.writestr(".gitignore", "bridge-config.json\n.dev.vars\n.wrangler/\nnode_modules/\n")
    return output.getvalue()


def decode_secret(value):
    value = value.strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return bytes.fromhex(value), os.environ.get("FAKE_TLS_HOST", "www.cloudflare.com")
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(raw) < 19 or raw[0] != 238:
        raise ValueError("A valid FakeTLS secret is required")
    host = raw[17:].decode("ascii")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise ValueError("Invalid FakeTLS hostname")
    return raw[1:17], host


def validate_settings(data):
    if not isinstance(data, dict) or not isinstance(data.get("enabled", False), bool):
        raise ValueError("Invalid settings")
    enabled = data.get("enabled", False)
    tag = str(data.get("ad_tag", "")).strip().lower()
    channel = str(data.get("channel", "")).strip().removeprefix("https://t.me/").lstrip("@")
    if tag and not re.fullmatch(r"[a-f0-9]{32}", tag):
        raise ValueError("Promotion tag must contain exactly 32 hexadecimal characters")
    if enabled and not tag:
        raise ValueError("Get a promotion tag from @MTProxybot before enabling sponsorship")
    if channel and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", channel):
        raise ValueError("Enter a public channel username, such as @mychannel")
    return {"enabled": enabled, "ad_tag": tag, "channel": channel}


def telemt_config(secret, settings, port, bridge=None, decoy_directory="/data/web-decoy"):
    key, host = decode_secret(secret)
    # JSON strings are also valid TOML basic strings for these validated fields.
    tag = settings["ad_tag"]
    routed = os.environ.get("TCP_ROUTER_PROXY_PROTOCOL") == "1"
    result = f'''[general]
use_middle_proxy = {str(settings.get("enabled", True)).lower()}
ad_tag = {json.dumps(tag)}
log_level = "normal"
middle_proxy_nat_probe = true

[general.modes]
classic = false
secure = false
tls = true

[server]
port = {port}
metrics_listen = "127.0.0.1:{int(os.environ.get('METRICS_PORT', '9090'))}"

[[server.listeners]]
ip = "{'127.0.0.1' if routed else '0.0.0.0'}"
proxy_protocol = {str(routed).lower()}

[server.api]
enabled = true
listen = "127.0.0.1:{int(os.environ.get('TELEMT_API_PORT', '9091'))}"
whitelist = ["127.0.0.1/32"]
read_only = true

[censorship]
tls_domain = {json.dumps(host)}
mask = true
tls_emulation = true

[access]
ignore_time_skew = false

[access.users]
owner = "{key.hex()}"
'''
    if bridge and bridge["enabled"]:
        worker_host = urlsplit(bridge["worker_url"]).hostname
        result += f'''
[[server.listeners]]
ip = "127.0.0.1"
port = {int(os.environ.get('WEB_LISTEN_PORT', '18080'))}
transport = "web"
proxy_protocol = false
web_client_ip_source = "x_forwarded_for"
web_trusted_proxy_cidrs = ["127.0.0.1/32"]

[web]
enabled = true
carrier = "https"
carriers = false
decoy_fasttrack_mode = "off"
http_connection_capacity_action = "drop"

[[web.vhosts]]
host = {json.dumps(worker_host)}
public_addr = "{bridge['public_ip']}:443"

[web.vhosts.decoy]
mode = "static_directory"
directory = {json.dumps(str(decoy_directory))}

[[web.vhosts.profiles]]
user = "owner"
secret_mode = "dd"
max_sessions = 64
max_streams = 2048
max_streams_per_session = 64
'''
    return result


class Proxy:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.resources = Resources(self.directory)
        self.path = self.directory / "sponsor.json"
        self.settings = validate_settings(json.loads(self.path.read_text())) if self.path.exists() else validate_settings({})
        self.process = None
        self.lock = threading.RLock()
        self.started = time.time()
        self.switching = False
        self.port = int(os.environ.get("MTPROTO_PORT", "3128"))
        secret_path = self.directory / "proxy-secret.json"
        self.secret = os.environ.get("SECRET", "").strip()
        if not self.secret:
            if secret_path.exists():
                self.secret = json.loads(secret_path.read_text())["secret"]
            else:
                host = os.environ.get("FAKE_TLS_HOST", "www.cloudflare.com")
                self.secret = "ee" + secrets.token_hex(16) + host.encode("ascii").hex()
        decode_secret(self.secret)
        write_private_json(secret_path, {"secret": self.secret})
        self.usage_path = self.directory / "usage.json"
        self.usage = json.loads(self.usage_path.read_text()) if self.usage_path.exists() else {"upload_bytes": 0, "download_bytes": 0, "since": int(time.time())}
        self.usage_last = (0, 0)
        self.usage_sampled = 0
        self.usage_saved = 0
        self.live_usage = {"available": False, "users": None, "connections": None}
        self.bridge_path = self.directory / "bridge.json"
        if self.bridge_path.exists():
            saved = json.loads(self.bridge_path.read_text())
            self.bridge = {**validate_bridge(saved), "token": saved["token"]}
        else:
            self.bridge = {**validate_bridge({}), "token": secrets.token_urlsafe(32)}
            write_private_json(self.bridge_path, self.bridge)

    def worker_name(self):
        # Stable per deployment, derived from its randomly generated private token.
        return "join-blueknight-net-tg-" + hashlib.sha256(self.bridge["token"].encode()).hexdigest()[:8]

    def hosting_origin(self):
        if os.environ.get("PANEL_PUBLIC_ORIGIN"):
            return validate_bridge({"worker_url": os.environ["PANEL_PUBLIC_ORIGIN"]})["worker_url"]
        return "https://" + os.environ.get("PANEL_PUBLIC_DOMAIN", "YOUR-APP.apps.bot-hosting.cloud")

    def apply_bridge(self, data):
        new = validate_bridge(data)
        if new["enabled"] and not new["public_ip"]:
            try:
                new["public_ip"] = socket.gethostbyname(urlsplit(new["worker_url"]).hostname)
                new = validate_bridge(new)
            except OSError:
                raise ValueError("Worker hostname could not be resolved")
        with self.lock:
            new["token"] = self.bridge["token"]
            old = self.bridge
            if all(new[k] == old[k] for k in ("worker_url", "enabled", "public_ip")):
                write_private_json(self.bridge_path, new)
                self.bridge = new
                return
            self.switching = True
            try:
                self.bridge = new
                self.stop()
                self.start()
                deadline = time.monotonic() + 40
                while not self.ready():
                    if self.process.poll() is not None or time.monotonic() > deadline:
                        raise ValueError("WEB proxy could not start; previous settings restored")
                    time.sleep(0.5)
                write_private_json(self.bridge_path, new)
            except Exception:
                self.bridge = old
                self.stop()
                self.start()
                raise
            finally:
                self.switching = False

    def start(self, settings=None):
        settings = settings if settings is not None else self.settings
        env = os.environ.copy()
        env["SECRET"] = self.secret
        path = self.directory / "telemt.toml"
        decoy = self.directory / "web-decoy"
        decoy.mkdir(exist_ok=True)
        (decoy / "index.html").write_text("<!doctype html><title>Welcome</title><h1>Welcome</h1>")
        path.write_text(telemt_config(self.secret, settings, self.port, self.bridge, decoy))
        path.chmod(0o600)
        command = [os.environ.get("TELEMT_BIN", "telemt"), str(path)]
        self.process = subprocess.Popen(command, env=env, cwd=self.directory)
        self.started = time.time()
        self.usage_last = (0, 0)
        self.usage_sampled = 0
        self.live_usage = {"available": False, "users": None, "connections": None}

    def stop(self):
        if self.process and self.process.poll() is None:
            self.sample_usage(force=True)
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def sample_usage(self, force=False):
        with self.lock:
            now = time.monotonic()
            if not force and now - self.usage_sampled < 5:
                return
            self.usage_sampled = now
            connection = http.client.HTTPConnection("127.0.0.1", int(os.environ.get("METRICS_PORT", "9090")), timeout=2)
            try:
                connection.request("GET", "/metrics")
                response = connection.getresponse()
                text = response.read(4 * 1024 * 1024 + 1)
                if response.status != 200 or len(text) > 4 * 1024 * 1024:
                    raise ValueError("Metrics unavailable")
                metric = parse_usage_metrics(text.decode())
                if not metric["valid"]:
                    raise ValueError("Metrics unavailable")
                current = (metric["upload"], metric["download"])
                for index, key in enumerate(("upload_bytes", "download_bytes")):
                    previous = self.usage_last[index]
                    self.usage[key] += current[index] - previous if current[index] >= previous else current[index]
                self.usage_last = current
                self.live_usage = {"available": True, "users": metric["users"], "connections": metric["connections"]}
            except (OSError, ValueError, http.client.HTTPException):
                self.live_usage = {"available": False, "users": None, "connections": None}
            finally:
                connection.close()
            if force or now - self.usage_saved >= 30:
                try:
                    write_private_json(self.usage_path, self.usage)
                    self.usage_saved = now
                except OSError:
                    pass

    def ready(self):
        if not self.process or self.process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                pass
            if self.bridge["enabled"]:
                with socket.create_connection(("127.0.0.1", int(os.environ.get("WEB_LISTEN_PORT", "18080"))), timeout=0.5):
                    pass
            return True
        except OSError:
            return False

    def apply(self, data):
        new = validate_settings(data)
        with self.lock:
            old = self.settings
            restart = old["enabled"] != new["enabled"] or (new["enabled"] and old["ad_tag"] != new["ad_tag"])
            if restart:
                self.switching = True
                try:
                    self.stop()
                    self.start(new)
                    deadline = time.monotonic() + 40
                    while not self.ready():
                        if self.process.poll() is not None or time.monotonic() > deadline:
                            raise ValueError("New engine did not start. Previous settings restored.")
                        time.sleep(0.5)
                except Exception:
                    self.stop()
                    self.start(old)
                    raise
                finally:
                    self.switching = False
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(new))
                tmp.chmod(0o600)
                os.replace(tmp, self.path)
            except OSError:
                if restart:
                    self.stop()
                    self.start(old)
                raise ValueError("Could not persist settings; previous engine restored")
            self.settings = new

    def status(self):
        self.sample_usage()
        key, host = decode_secret(self.secret)
        public_host = os.environ.get("PUBLIC_HOST", "")
        public_port = os.environ.get("PUBLIC_PORT", os.environ.get("SERVER_PORT", ""))
        full = (b"\xee" + key + host.encode()).hex()
        params = f"server={public_host}&port={public_port}&secret={full}"
        web_params = f"server={urlsplit(self.bridge['worker_url']).hostname or ''}&secret=dd{key.hex()}"
        return {"running": self.ready(), "engine": "Telemt",
                "uptime": int(time.time() - self.started), "host": public_host, "port": public_port,
                "tls_host": host, "settings": self.settings,
                "tg_link": "tg://proxy?" + params, "web_link": "https://t.me/proxy?" + params,
                "registration_secret": key.hex(),
                "resources": self.resources.snapshot(),
                "usage": {**self.usage, **self.live_usage, "total_bytes": self.usage["upload_bytes"] + self.usage["download_bytes"]},
                "bridge": {"worker_url": self.bridge["worker_url"], "enabled": self.bridge["enabled"],
                           "worker_name": self.worker_name(), "hosting_origin": self.hosting_origin(),
                           "public_ip": self.bridge["public_ip"], "configured": self.bridge["enabled"],
                           "tg_link": "tg://webproxy?" + web_params if self.bridge["enabled"] else ""},
                "persistent": os.environ.get("PANEL_PERSISTENT_DATA") == "1"}


class App:
    def __init__(self, proxy, password_hash, setup_code=None):
        self.proxy = proxy
        self.password_hash = password_hash
        self.sessions = {}
        self.attempts = []
        self.lock = threading.Lock()
        self.bridge_slots = threading.BoundedSemaphore(128)
        self.setup_code = setup_code

    def configure(self, code, password):
        with self.lock:
            if self.password_hash or not self.setup_code:
                raise ValueError("This deployment is already configured")
            now = time.time()
            self.attempts = [x for x in self.attempts if now - x < 60]
            if len(self.attempts) >= 10:
                raise ValueError("Too many attempts. Wait one minute")
            self.attempts.append(now)
            if not hmac.compare_digest(hashlib.sha256(code.encode()).digest(), hashlib.sha256(self.setup_code.encode()).digest()):
                raise ValueError("Incorrect setup code")
            if not 8 <= len(password) <= 256:
                raise ValueError("Choose a password between 8 and 256 characters")
            salt = secrets.token_hex(16)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()
            stored = "pbkdf2_sha256$310000$" + salt + "$" + digest
            write_private_json(self.proxy.directory / "owner.json", {"password_hash": stored})
            self.password_hash = stored
            self.setup_code = None
            try:
                (self.proxy.directory / "setup-code.json").unlink(missing_ok=True)
            except OSError:
                pass  # The saved owner hash and configured state invalidate this code.
            self.attempts = []

    def login(self, password):
        if not self.password_hash:
            return None
        with self.lock:
            now = time.time()
            self.attempts = [x for x in self.attempts if now - x < 60]
            if len(self.attempts) >= 10:
                return None
            self.attempts.append(now)
        if self.password_hash.startswith("pbkdf2_sha256$"):
            _, rounds, salt, expected = self.password_hash.split("$")
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        else:
            expected = self.password_hash
            actual = hashlib.sha256(password.encode()).hexdigest()
        if not hmac.compare_digest(actual, expected):
            return None
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > now}
            self.sessions[token] = {"expires": now + 8 * 3600, "csrf": csrf}
        return token


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log credentials, cookies, or links.

        def reply(self, status, body, content_type="application/json", cookie=None, filename=None):
            raw = json.dumps(body).encode() if isinstance(body, dict) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(raw)

        def session(self):
            cookies = http.cookies.SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except http.cookies.CookieError:
                return None
            token = cookies.get("panel_session")
            with app.lock:
                session = app.sessions.get(token.value) if token else None
            return session if session and session["expires"] > time.time() else None

        def relay_web(self):
            """Only the Worker can reach the fixed private WEB listener; never an open proxy."""
            state = app.proxy.bridge
            token = self.headers.get("X-Bridge-Token", "")
            if not state["enabled"] or not hmac.compare_digest(token, state["token"]):
                return self.reply(404, b"Not found", "text/plain")
            if not app.bridge_slots.acquire(blocking=False):
                return self.reply(503, b"Busy", "text/plain")
            upstream = None
            try:
                self.connection.settimeout(15)
                if self.headers.get("Transfer-Encoding"):
                    return self.reply(400, b"Content-Length required", "text/plain")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 1024 * 1024:
                    return self.reply(413, b"Request too large", "text/plain")
                body = self.rfile.read(size)
                if len(body) != size:
                    return self.reply(400, b"Incomplete body", "text/plain")
                client_ip = str(ipaddress.ip_address(self.headers.get("X-Bridge-Client-IP", "")))
                blocked = {"host", "connection", "content-length", "transfer-encoding", "upgrade", "cookie", "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-bridge-token", "x-bridge-client-ip", "accept-encoding", "proxy-authorization", "proxy-connection", "te", "trailer", "keep-alive"}
                headers = {k: v for k, v in self.headers.items() if k.lower() not in blocked}
                headers.update({"Host": urlsplit(state["worker_url"]).hostname, "X-Forwarded-For": client_ip,
                                "Content-Length": str(size), "Connection": "close", "Accept-Encoding": "identity"})
                path = self.path[len("/_webbridge"):]
                if not path.startswith("/") or path.startswith("//"):
                    return self.reply(400, b"Invalid path", "text/plain")
                upstream = http.client.HTTPConnection("127.0.0.1", int(os.environ.get("WEB_LISTEN_PORT", "18080")), timeout=40)
                upstream.request(self.command, path, body=body, headers=headers)
                response = upstream.getresponse()
                raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    return self.reply(502, b"Response too large", "text/plain")
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in {"connection", "transfer-encoding", "content-length", "keep-alive", "set-cookie"}:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(raw)
            except (ValueError, OSError, http.client.HTTPException):
                self.reply(502, b"Bridge unavailable", "text/plain")
            finally:
                if upstream:
                    upstream.close()
                app.bridge_slots.release()

        def do_HEAD(self):
            if self.path.startswith("/_webbridge/"):
                return self.relay_web()
            return self.reply(404, b"", "text/plain")

        def do_DELETE(self):
            if self.path.startswith("/_webbridge/"):
                return self.relay_web()
            return self.reply(404, b"Not found", "text/plain")

        def do_GET(self):
            if self.path.startswith("/_webbridge/"):
                return self.relay_web()
            path = urlsplit(self.path).path
            if path == "/api/setup/status":
                return self.reply(200, {"required": not bool(app.password_hash)})
            if path == "/health":
                return self.reply(200 if app.proxy.ready() else 503, b"ok\n" if app.proxy.ready() else b"starting\n", "text/plain")
            if path in ("/", "/panel", "/panel/"):
                return self.reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path in ("/panel/app.js", "/panel/style.css", "/panel/blueknight.css"):
                name = path.rsplit("/", 1)[-1]
                return self.reply(200, (ROOT / name).read_bytes(), "text/javascript" if name.endswith("js") else "text/css")
            if path in ("/panel/assets/bg.jpg", "/panel/assets/cozybg.jpg", "/panel/assets/logo.png"):
                name = path.rsplit("/", 1)[-1]
                return self.reply(200, (ROOT / "assets" / name).read_bytes(), "image/png" if name.endswith("png") else "image/jpeg")
            session = self.session()
            if path == "/api/status":
                if not session:
                    return self.reply(401, {"error": "Sign in required"})
                return self.reply(200, {**app.proxy.status(), "csrf": session["csrf"]})
            if path == "/api/bridge/bundle":
                if not session:
                    return self.reply(401, {"error": "Sign in required"})
                try:
                    return self.reply(200, bridge_bundle(app.proxy), "application/zip", filename="blue-knight-bridge.zip")
                except Exception:
                    return self.reply(500, {"error": "Could not create bridge bundle"})
            if path == "/api/bridge/standalone":
                if not session:
                    return self.reply(401, {"error": "Sign in required"})
                return self.reply(200, (BRIDGE_ROOT / "worker-standalone.mjs").read_bytes(), "text/javascript; charset=utf-8", filename="blue-knight-worker.mjs")
            if path == "/api/bridge/token":
                if not session:
                    return self.reply(401, {"error": "Sign in required"})
                return self.reply(200, {"token": app.proxy.bridge["token"]})
            return self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if self.path.startswith("/_webbridge/"):
                return self.relay_web()
            self.connection.settimeout(10)
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                return self.reply(403, {"error": "Cross-origin request rejected"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    return self.reply(413, {"error": "Invalid request size"})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError()
            except (ValueError, OSError):
                return self.reply(400, {"error": "Invalid request"})
            path = urlsplit(self.path).path
            if path == "/api/setup":
                code, password = data.get("code"), data.get("password")
                if not isinstance(code, str) or len(code) > 128 or not isinstance(password, str):
                    return self.reply(400, {"error": "Invalid setup request"})
                try:
                    app.configure(code, password)
                    return self.reply(200, {"ok": True})
                except ValueError as error:
                    return self.reply(400, {"error": str(error)})
                except OSError:
                    return self.reply(500, {"error": "Could not save owner password"})
            if path == "/api/login":
                password = data.get("password", "")
                if not isinstance(password, str) or len(password) > 256:
                    return self.reply(400, {"error": "Invalid password"})
                token = app.login(password)
                if not token:
                    return self.reply(401, {"error": "Incorrect password or too many attempts. Wait one minute."})
                secure = "; Secure" if os.environ.get("PANEL_PUBLIC_ORIGIN", "").startswith("https://") else ""
                return self.reply(200, {"ok": True}, cookie=f"panel_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}")
            session = self.session()
            if not session or not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                return self.reply(403, {"error": "Session expired; sign in again"})
            if path == "/api/settings":
                try:
                    app.proxy.apply(data)
                    return self.reply(200, {"ok": True})
                except ValueError as error:
                    return self.reply(400, {"error": str(error)})
                except Exception:
                    return self.reply(500, {"error": "Could not apply settings"})
            if path == "/api/bridge/settings":
                try:
                    app.proxy.apply_bridge(data)
                    return self.reply(200, {"ok": True})
                except ValueError as error:
                    return self.reply(400, {"error": str(error)})
                except Exception:
                    return self.reply(500, {"error": "Could not save bridge settings"})
            if path == "/api/logout":
                with app.lock:
                    for token, value in list(app.sessions.items()):
                        if value is session:
                            del app.sessions[token]
                return self.reply(200, {"ok": True}, cookie="panel_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            return self.reply(404, {"error": "Not found"})
    return Handler


def main():
    os.umask(0o077)
    proxy = Proxy(os.environ.get("PANEL_DATA_DIR", "/data"))
    setup_code = None
    if os.environ.get("PANEL_PASSWORD_HASH") or os.environ.get("PANEL_PASSWORD"):
        try:
            password_hash = panel_password_hash()
        except ValueError as error:
            raise SystemExit(str(error))
    elif (proxy.directory / "owner.json").exists():
        password_hash = json.loads((proxy.directory / "owner.json").read_text())["password_hash"]
    else:
        password_hash = ""
        setup_path = proxy.directory / "setup-code.json"
        if not setup_path.exists():
            write_private_json(setup_path, {"code": secrets.token_urlsafe(24)})
        setup_code = json.loads(setup_path.read_text())["code"]
        print("[setup] Open /panel/ and enter this one-time setup code: " + setup_code, flush=True)
    proxy.resources.snapshot()
    proxy.start()
    app = App(proxy, password_hash, setup_code)
    port = int(os.environ.get("HTTP_PORT") or os.environ.get("PORT", "8080"))
    if port == proxy.port:
        proxy.stop()
        raise SystemExit("HTTP and MTProto ports must be different")
    server = ThreadingHTTPServer(("0.0.0.0", port), handler_for(app))
    def stop(*_):
        with proxy.lock:
            proxy.sample_usage(force=True)
        proxy.stop()
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[panel] listening on HTTP port {port}; admin authentication required", flush=True)
    while True:
        time.sleep(2)
        proxy.resources.snapshot()
        if not proxy.switching:
            with proxy.lock:
                if proxy.process.poll() is not None:
                    print("[panel] proxy exited; restarting", flush=True)
                    proxy.start()
                else:
                    proxy.sample_usage()


if __name__ == "__main__":
    main()
