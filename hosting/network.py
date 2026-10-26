"""Discover and verify this deployment's public TCP endpoint without account keys."""
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import urllib.request
from urllib.parse import urlsplit


def panel_origin(host):
    """Only infer HTTPS origins owned by the hosting platform, never arbitrary Host values."""
    try:
        parsed = urlsplit("https://" + (host or ""))
        if parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.path or parsed.query or parsed.fragment:
            return ""
        if re.fullmatch(r"[a-z0-9-]+\.apps\.bot-hosting\.(?:cloud|net)", parsed.hostname or ""):
            return "https://" + parsed.hostname
    except ValueError:
        pass
    return ""


class PublicNetwork:
    def __init__(self, directory, public_port):
        self.path = Path(directory) / "network.json"
        self.saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.public_port = public_port
        self.host = ""
        self.origin = self.saved.get("origin", "")
        self.probe_id = secrets.token_hex(24)
        self.lock = threading.RLock()

    def persist(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"host": self.host, "origin": self.origin}))
        temporary.chmod(0o600)
        os.replace(temporary, self.path)

    def observe_owner_origin(self, host):
        origin = panel_origin(host)
        if not origin:
            return
        with self.lock:
            if not self.origin:
                self.origin = origin
                try:
                    self.persist()
                except OSError:
                    pass

    def verify(self, host):
        if not host or ".apps." in host or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
            return False
        try:
            addresses = socket.getaddrinfo(host, self.public_port, socket.AF_INET, socket.SOCK_STREAM)
            for address in dict.fromkeys(item[4][0] for item in addresses):
                if not ipaddress.ip_address(address).is_global:
                    continue
                connection = http.client.HTTPConnection(address, self.public_port, timeout=3)
                try:
                    connection.request("GET", "/_network/probe")
                    response = connection.getresponse()
                    raw = response.read(1025)
                    if response.status == 200 and len(raw) <= 1024 and json.loads(raw).get("instance") == self.probe_id:
                        return True
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                finally:
                    connection.close()
        except (OSError, ValueError):
            pass
        return False

    def discover_once(self):
        candidates = [os.environ.get("PUBLIC_HOST", ""), os.environ.get("SERVER_IP", ""), self.saved.get("host", "")]
        seen = set()
        def try_host(host):
            if host in seen:
                return False
            seen.add(host)
            if not self.verify(host):
                return False
            with self.lock:
                self.host = host
                self.persist()
            return True
        for candidate in candidates:
            if try_host(candidate):
                return True
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for url in ("https://api4.ipify.org", "https://ipv4.icanhazip.com"):
            try:
                with opener.open(url, timeout=5) as response:
                    address = response.read(65).decode("ascii").strip()
                parsed = ipaddress.ip_address(address)
                if parsed.version == 4 and parsed.is_global and try_host(address):
                    return True
            except (OSError, ValueError, UnicodeError):
                pass
        return False

    def discover(self):
        if not 1 <= self.public_port <= 65535:
            return
        while True:
            try:
                if self.discover_once():
                    print("[network] Public proxy address detected and verified", flush=True)
                    return
            except OSError:
                pass
            print("[network] Public address not yet verified; retrying automatically", flush=True)
            time.sleep(30)
