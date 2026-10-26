import hashlib
from http.client import HTTPConnection
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import tomllib
import unittest
import zipfile
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("panel_server", ROOT / "panel/server.py")
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
SECRET = "ee" + "12" * 16 + b"www.cloudflare.com".hex()


class FakeProxy:
    bridge = {"enabled": True, "token": "test-token", "worker_url": "https://worker.example"}

    def hosting_origin(self):
        return "https://demo.apps.bot-hosting.cloud"
    def ready(self):
        return True

    def status(self):
        return {"running": True, "secret": "private-example"}

    def apply(self, data):
        panel.validate_settings(data)


class PanelTests(unittest.TestCase):
    def test_fresh_secret_generated_once_and_existing_override_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {}, clear=True):
            first = panel.Proxy(directory)
            key, host = panel.decode_secret(first.secret)
            self.assertEqual(len(key), 16)
            self.assertEqual(host, "www.cloudflare.com")
            self.assertEqual(panel.Proxy(directory).secret, first.secret)
            with patch.dict(panel.os.environ, {"SECRET": SECRET}):
                self.assertEqual(panel.Proxy(directory).secret, SECRET)
            self.assertEqual(panel.Proxy(directory).secret, SECRET)

    def test_password_options_and_hash_precedence(self):
        with patch.dict(panel.os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                panel.panel_password_hash()
            with patch.dict(panel.os.environ, {"PANEL_PASSWORD": "short"}):
                with self.assertRaises(ValueError):
                    panel.panel_password_hash()
            with patch.dict(panel.os.environ, {"PANEL_PASSWORD": "example-test-password"}):
                self.assertEqual(panel.panel_password_hash(), hashlib.sha256(b"example-test-password").hexdigest())
                with patch.dict(panel.os.environ, {"PANEL_PASSWORD_HASH": "ab" * 32}):
                    self.assertEqual(panel.panel_password_hash(), "ab" * 32)
                with patch.dict(panel.os.environ, {"PANEL_PASSWORD_HASH": "invalid"}):
                    with self.assertRaises(ValueError):
                        panel.panel_password_hash()

    def test_bridge_validation_and_private_bundle(self):
        for url in ("http://worker.example", "https://worker.example/path", "https://user:pass@worker.example", "https://worker.example?token=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                panel.validate_bridge({"worker_url": url})
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {"SECRET": SECRET, "PUBLIC_HOST": "node.bot-hosting.cloud", "PUBLIC_PORT": "25745"}):
            proxy = panel.Proxy(directory)
            original_token = proxy.bridge["token"]
            with patch.object(proxy, "start") as start, patch.object(proxy, "stop"), patch.object(proxy, "ready", return_value=True):
                proxy.apply_bridge({"worker_url": "https://bridge.example", "local_port": 1443})
                start.assert_called_once()
            restored = panel.Proxy(directory)
            self.assertEqual(restored.bridge["token"], original_token)
            with zipfile.ZipFile(io.BytesIO(panel.bridge_bundle(restored))) as archive:
                config = json.loads(archive.read("bridge-config.json"))
                worker = json.loads(archive.read("wrangler.jsonc"))
                self.assertEqual(config["token"], original_token)
                self.assertEqual(config["worker_url"], "https://bridge.example")
                self.assertIn("UPSTREAM_ORIGIN", worker["vars"])
                self.assertRegex(worker["name"], r"^join-blueknight-net-tg-[a-f0-9]{8}$")
                self.assertEqual(worker["name"], proxy.worker_name())
                self.assertNotIn("helper.mjs", archive.namelist())
                self.assertNotIn(original_token, archive.read("worker.mjs").decode())
                self.assertNotIn("PANEL_PASSWORD_HASH", archive.read("bridge-config.json").decode())
    def test_native_web_configuration_and_link(self):
        bridge = {"enabled": True, "worker_url": "https://worker.example", "public_ip": "1.1.1.1"}
        data = tomllib.loads(panel.telemt_config(SECRET, {"enabled": False, "ad_tag": ""}, 3128, bridge))
        self.assertFalse(data["general"]["use_middle_proxy"])
        self.assertEqual(data["server"]["listeners"][1]["ip"], "127.0.0.1")
        self.assertEqual(data["web"]["carrier"], "https")
        self.assertEqual(data["web"]["vhosts"][0]["profiles"][0]["secret_mode"], "dd")
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {"SECRET": SECRET}):
            proxy = panel.Proxy(directory)
            proxy.bridge.update(bridge)
            link = proxy.status()["bridge"]["tg_link"]
            self.assertEqual(link, "tg://webproxy?server=worker.example&secret=dd" + "12" * 16)

    def test_failed_web_enable_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {"SECRET": SECRET}):
            proxy = panel.Proxy(directory)
            proxy.process = Mock()
            proxy.process.poll.return_value = 1
            with patch.object(proxy, "stop"), patch.object(proxy, "start"), patch.object(proxy, "ready", return_value=False):
                with self.assertRaises(ValueError):
                    proxy.apply_bridge({"enabled": True, "worker_url": "https://worker.example", "public_ip": "1.1.1.1"})
            self.assertFalse(proxy.bridge["enabled"])
            self.assertFalse(panel.Proxy(directory).bridge["enabled"])

    def test_secret_preserved(self):
        key, host = panel.decode_secret(SECRET)
        self.assertEqual(key.hex(), "12" * 16)
        self.assertEqual(host, "www.cloudflare.com")

    def test_telemt_config(self):
        data = tomllib.loads(panel.telemt_config(SECRET, {"ad_tag": "ab" * 16}, 3128))
        self.assertTrue(data["general"]["use_middle_proxy"])
        self.assertEqual(data["general"]["ad_tag"], "ab" * 16)
        self.assertEqual(data["access"]["users"]["owner"], "12" * 16)
        self.assertFalse(data["access"]["ignore_time_skew"])
        self.assertEqual(data["server"]["api"]["listen"], "127.0.0.1:9091")

    def test_settings_validation(self):
        for value in ({"enabled": True}, {"enabled": "true"}, {"channel": '<script>'}, {"ad_tag": '"\nmalicious'}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                panel.validate_settings(value)
        self.assertEqual(panel.validate_settings({"channel": "https://t.me/mychannel"})["channel"], "mychannel")

    def test_settings_persist_without_restart_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {"SECRET": SECRET}):
            proxy = panel.Proxy(directory)
            with patch.object(proxy, "stop") as stop:
                proxy.apply({"enabled": False, "channel": "mychannel", "ad_tag": "ab" * 16})
                stop.assert_not_called()
            self.assertEqual(panel.Proxy(directory).settings["channel"], "mychannel")

    def test_failed_engine_switch_restores_previous_engine(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {"SECRET": SECRET}):
            proxy = panel.Proxy(directory)
            proxy.process = Mock()
            proxy.process.poll.return_value = 1
            with patch.object(proxy, "stop"), patch.object(proxy, "start") as start, patch.object(proxy, "ready", return_value=False):
                with self.assertRaises(ValueError):
                    proxy.apply({"enabled": True, "ad_tag": "ab" * 16})
                self.assertEqual(start.call_count, 2)
            self.assertFalse(proxy.settings["enabled"])
            self.assertFalse(proxy.path.exists())


class ResourceTests(unittest.TestCase):
    def test_deployment_disk_usage_uses_own_files_and_configured_quota(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(panel.os.environ, {"PANEL_STORAGE_ROOT": folder, "PANEL_STORAGE_LIMIT_MB": "1"}):
            (Path(folder) / "data.bin").write_bytes(b"x" * 100)
            result = panel.Resources(folder).snapshot()
            self.assertEqual(result["disk_scope"], "deployment")
            self.assertEqual(result["disk_used"], 100)
            self.assertEqual(result["disk_total"], 1024 * 1024)

    def test_container_limits_cpu_interval_and_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "cpu.max").write_text("50000 100000")
            (root / "cpu.stat").write_text("usage_usec 1000000")
            (root / "memory.current").write_text("256")
            (root / "memory.max").write_text("1024")
            reader = panel.Resources(folder, root)
            with patch.object(panel.time, "monotonic", return_value=10):
                first = reader.snapshot()
            self.assertIsNone(first["cpu_percent"])
            self.assertEqual(first["cpu_cores"], 0.5)
            self.assertEqual(first["memory_percent"], 25)
            self.assertGreater(first["disk_total"], 0)
            (root / "cpu.stat").write_text("usage_usec 1500000")
            with patch.object(panel.time, "monotonic", return_value=12):
                self.assertEqual(reader.snapshot()["cpu_percent"], 50)

    def test_missing_container_counters_do_not_show_host_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = panel.Resources(folder, Path(folder) / "missing")
            data = reader.snapshot()
            self.assertIsNone(data["cpu_percent"])
            self.assertIsNone(data["memory_percent"])
            self.assertIsNone(data["memory_used"])
            self.assertGreater(data["disk_total"], 0)


class UsageTests(unittest.TestCase):
    def test_telemt_counts_are_not_confused_with_connections_or_decoys(self):
        text = """# HELP telemt_user_connections_current Per-user active connections
telemt_user_connections_current{user="owner"} 9
telemt_user_unique_ips_current{user="owner"} 3
telemt_user_octets_from_client_total{user="owner"} 100
telemt_user_octets_to_client_total{user="owner"} 250
telemt_user_connections_total{user="owner"} 3000
unrelated_bytes_total 999999
"""
        result = panel.parse_usage_metrics(text)
        self.assertEqual(result, {"connections": 9, "users": 3, "upload": 100, "download": 250, "valid": True})
        self.assertFalse(panel.parse_usage_metrics("not metrics")["valid"])
        self.assertEqual(panel.parse_usage_metrics("# HELP telemt_user_connections_current active")["connections"], 0)

    def test_usage_deltas_restart_persistence_and_unavailable_metrics(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {"SECRET": SECRET}):
            proxy = panel.Proxy(directory)
            with patch.object(panel.http.client, "HTTPConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status = 200
                def metrics(up, down):
                    return ('# HELP telemt_user_connections_current Active connections\ntelemt_user_octets_from_client_total{user="owner"} '+str(up)+'\ntelemt_user_octets_to_client_total{user="owner"} '+str(down)).encode()
                response.read.return_value = metrics(100, 200)
                proxy.sample_usage(force=True)
                proxy.sample_usage(force=True)
                self.assertEqual(proxy.usage["upload_bytes"], 100)
                response.read.return_value = metrics(125, 240)
                proxy.sample_usage(force=True)
                self.assertEqual(proxy.usage["download_bytes"], 240)
                response.status = 503
                proxy.sample_usage(force=True)
                self.assertFalse(proxy.live_usage["available"])
                restored = panel.Proxy(directory)
                self.assertEqual(restored.usage["upload_bytes"], 125)
                response.status = 200
                response.read.return_value = metrics(10, 30)
                restored.sample_usage(force=True)
                self.assertEqual(restored.usage["upload_bytes"], 135)
                self.assertEqual(restored.usage["download_bytes"], 270)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.app = panel.App(FakeProxy(), hashlib.sha256(b"test-password").hexdigest())
        self.server = panel.ThreadingHTTPServer(("127.0.0.1", 0), panel.handler_for(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, data=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        h = headers or {}
        connection.request("POST" if data is not None else "GET", path, body=json.dumps(data) if data is not None else None, headers=h)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_private_status_and_public_health(self):
        self.assertEqual(self.request("/api/status")[0], 401)
        self.assertEqual(self.request("/api/bridge/bundle")[0], 401)
        self.assertEqual(self.request("/api/bridge/standalone")[0], 401)
        self.assertEqual(self.request("/api/bridge/token")[0], 401)
        self.assertEqual(self.request("/health")[0], 200)
        self.assertNotIn(b"private-example", self.request("/")[2])
        self.assertEqual(self.request("/../server.py")[0], 404)

    def test_first_visit_password_setup_requires_code_and_cannot_reset_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            self.app.proxy.directory = Path(directory)
            self.app.password_hash = ""
            self.app.setup_code = "synthetic-setup-code"
            code, _, body = self.request("/api/setup/status")
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(body)["required"])
            self.assertNotIn(b"synthetic-setup-code", body)
            self.assertEqual(self.request("/api/setup", {"code": "wrong", "password": "Eight123"})[0], 400)
            self.assertEqual(self.request("/api/setup", {"code": "synthetic-setup-code", "password": "short"})[0], 400)
            self.assertFalse((Path(directory) / "owner.json").exists())
            self.assertEqual(self.request("/api/setup", {"code": "synthetic-setup-code", "password": "Eight123"}, {"Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.request("/api/setup", {"code": "synthetic-setup-code", "password": "Eight123"})[0], 200)
            stored = json.loads((Path(directory) / "owner.json").read_text())["password_hash"]
            self.assertTrue(stored.startswith("pbkdf2_sha256$"))
            self.assertNotIn("Eight123", stored)
            self.assertFalse(json.loads(self.request("/api/setup/status")[2])["required"])
            self.assertEqual(self.request("/api/setup", {"code": "synthetic-setup-code", "password": "changed123"})[0], 400)
            self.assertEqual(self.request("/api/login", {"password": "Eight123"})[0], 200)
            restored = panel.App(self.app.proxy, stored)
            self.assertIsNone(restored.login("wrong"))
            self.assertIsNotNone(restored.login("Eight123"))

    def test_origin_relay_requires_worker_token(self):
        self.assertEqual(self.request("/_webbridge/")[0], 404)
        self.assertEqual(self.request("/_webbridge/api/v1/down", headers={"X-Bridge-Token": "bad"})[0], 404)
        with patch.object(panel.http.client, "HTTPConnection") as factory:
            # Use the real client outside the patched module reference.
            client = HTTPConnection("127.0.0.1", self.port, timeout=3)
            reply = factory.return_value.getresponse.return_value
            reply.status = 200
            reply.read.return_value = b"bridge document"
            reply.getheaders.return_value = [("Content-Type", "text/html"), ("Content-Security-Policy", "script-src 'nonce-example'")]
            client.request("GET", "/_webbridge/?bridge=example", headers={"X-Bridge-Token": "test-token", "X-Bridge-Client-IP": "1.2.3.4", "X-Forwarded-For": "attacker", "Cookie": "private"})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Security-Policy"), "script-src 'nonce-example'")
            self.assertEqual(response.read(), b"bridge document")
            args = factory.return_value.request.call_args
            self.assertEqual(args.args[1], "/?bridge=example")
            self.assertEqual(args.kwargs["headers"]["X-Forwarded-For"], "1.2.3.4")
            self.assertNotIn("Cookie", args.kwargs["headers"])
            client.close()

    def test_visual_assets_are_served_without_exposing_other_files(self):
        self.assertEqual(self.request("/panel/blueknight.css")[0], 200)
        code, headers, body = self.request("/panel/assets/logo.png")
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))
        self.assertEqual(self.request("/panel/assets/../server.py")[0], 404)
        self.assertEqual(self.request("/panel/NOTICE.md")[0], 404)

    def test_login_csrf_and_logout(self):
        self.assertEqual(self.request("/api/login", {"password": "wrong"})[0], 401)
        code, headers, _ = self.request("/api/login", {"password": "test-password"})
        self.assertEqual(code, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        code, _, body = self.request("/api/status", headers={"Cookie": cookie})
        self.assertEqual(code, 200)
        csrf = json.loads(body)["csrf"]
        code, _, worker = self.request("/api/bridge/standalone", headers={"Cookie": cookie})
        self.assertEqual(code, 200)
        self.assertIn(b"export default", worker)
        self.assertIn(b"test-token", worker)
        self.assertIn(b"https://demo.apps.bot-hosting.cloud", worker)
        self.assertIn(b"PRIVATE deployment file", worker)
        self.assertNotIn(b"test-token", (ROOT / "bridge/worker-standalone.mjs").read_bytes())
        code, _, token = self.request("/api/bridge/token", headers={"Cookie": cookie})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(token)["token"], "test-token")
        self.assertEqual(self.request("/api/settings", {"enabled": False}, {"Cookie": cookie})[0], 403)
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
        self.assertEqual(self.request("/api/settings", {"enabled": False, "channel": "mychannel"}, headers)[0], 200)
        self.assertEqual(self.request("/api/logout", {}, headers)[0], 200)
        self.assertEqual(self.request("/api/status", headers={"Cookie": cookie})[0], 401)

    def test_cross_origin_and_rate_limit(self):
        self.assertEqual(self.request("/api/login", {"password": "test-password"}, {"Origin": "https://evil.example"})[0], 403)
        for _ in range(10):
            self.app.login("wrong")
        self.assertIsNone(self.app.login("test-password"))

    def test_secure_production_cookie(self):
        with patch.dict(panel.os.environ, {"PANEL_PUBLIC_ORIGIN": "https://example.apps.bot-hosting.cloud"}):
            _, headers, _ = self.request("/api/login", {"password": "test-password"})
            self.assertIn("; Secure", headers["Set-Cookie"])
        with patch.dict(panel.os.environ, {"PANEL_PUBLIC_ORIGIN": "https://my-app.apps.bot-hosting.cloud"}):
            _, headers, _ = self.request("/api/login", {"password": "test-password"})
            self.assertIn("; Secure", headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
