"""Bot-Hosting Python entry point. No Docker or administrator privileges needed."""
import asyncio
import hashlib
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tarfile
import urllib.request

from hosting.port_router import PortRouter

ROOT = Path(__file__).resolve().parent
VERSION = "3.5.14"


def download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": "BlueKnightProxy/1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        size = 0
        while chunk := response.read(65536):
            size += len(chunk)
            if size > 64 * 1024 * 1024:
                raise ValueError("Engine download exceeded size limit")
            output.write(chunk)


def install_engine():
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64"}.get(platform.machine().lower())
    if platform.system() != "Linux" or not arch:
        raise ValueError("Bot-Hosting entry point requires Linux x86_64 or aarch64")
    directory = ROOT / ".cache" / ("telemt-" + VERSION)
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "telemt"
    if binary.exists():
        return binary
    asset = f"telemt-{arch}-linux-musl.tar.gz"
    base = f"https://github.com/telemt/telemt/releases/download/{VERSION}/"
    archive = directory / asset
    checksum = directory / (asset + ".sha256")
    print("[hosting] Downloading pinned Telemt engine", flush=True)
    try:
        download(base + asset, archive)
        download(base + asset + ".sha256", checksum)
        expected = checksum.read_text().split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Invalid engine checksum")
        digest = hashlib.sha256()
        with archive.open("rb") as source:
            while chunk := source.read(65536):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("Engine checksum verification failed")
        # Extract only the engine bytes; never trust archive paths or links.
        with tarfile.open(archive) as bundle:
            member = next(item for item in bundle if item.isfile() and Path(item.name).name == "telemt")
            if member.size > 96 * 1024 * 1024:
                raise ValueError("Engine binary too large")
            with bundle.extractfile(member) as source, binary.with_suffix(".tmp").open("wb") as target:
                while chunk := source.read(65536):
                    target.write(chunk)
        binary.with_suffix(".tmp").chmod(0o700)
        os.replace(binary.with_suffix(".tmp"), binary)
        return binary
    finally:
        archive.unlink(missing_ok=True)
        checksum.unlink(missing_ok=True)


async def serve(public_port, http_port, proxy_port, child):
    router = PortRouter(http_port, proxy_port, proxy_protocol=True)
    server = await asyncio.start_server(router.handle, "0.0.0.0", public_port, backlog=128)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    print(f"[hosting] HTTP and MTProto share public port {public_port}", flush=True)
    async with server:
        while child.poll() is None and not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except asyncio.TimeoutError:
                pass
    if child.poll() not in (None, 0):
        raise RuntimeError("Panel process exited; see deployment logs")


def main():
    os.umask(0o077)
    public = int(os.environ.get("SERVER_PORT", "8080"))
    if not 1 <= public <= 65535:
        raise ValueError("Invalid allocated SERVER_PORT")
    http = 8081 if public == 8080 else 8080
    proxy = 3129 if public == 3128 else 3128
    env = os.environ.copy()
    env.update(TELEMT_BIN=str(install_engine()), PANEL_DATA_DIR=str(ROOT / ".data"),
               PANEL_PERSISTENT_DATA="1", PORT=str(http), HTTP_PORT=str(http), MTPROTO_PORT=str(proxy),
               TCP_ROUTER_PROXY_PROTOCOL="1", METRICS_PORT=str(9092 if public == 9090 else 9090),
               TELEMT_API_PORT=str(9093 if public == 9091 else 9091),
               WEB_LISTEN_PORT=str(18081 if public == 18080 else 18080))
    # The platform allocation is authoritative; users no longer enter this port.
    env["PUBLIC_PORT"] = str(public)
    env.setdefault("PANEL_STORAGE_LIMIT_MB", "512")
    env["PANEL_STORAGE_ROOT"] = str(ROOT)
    child = subprocess.Popen([sys.executable, "-u", str(ROOT / "panel" / "server.py")], env=env, cwd=ROOT)
    try:
        asyncio.run(serve(public, http, proxy, child))
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
