import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hosting.network import PublicNetwork, panel_origin

spec = importlib.util.spec_from_file_location("panel_network_tests", ROOT / "panel/server.py")
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)


class NetworkTests(unittest.TestCase):
    def test_origin_allowlist(self):
        self.assertEqual(panel_origin("demo.apps.bot-hosting.cloud"), "https://demo.apps.bot-hosting.cloud")
        for host in ("evil.example", "demo.apps.bot-hosting.cloud.evil.example", "user@demo.apps.bot-hosting.cloud", "demo.apps.bot-hosting.cloud:1234", "demo.apps.bot-hosting.cloud/path"):
            self.assertEqual(panel_origin(host), "")

    def test_public_probe_requires_own_instance_and_rejects_app_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            network = PublicNetwork(directory, 25476)
            addresses = [(2, 1, 6, "", ("1.1.1.1", 25476))]
            with patch("hosting.network.socket.getaddrinfo", return_value=addresses), patch("hosting.network.http.client.HTTPConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status = 200
                response.read.return_value = json.dumps({"instance": "some-other-app"}).encode()
                self.assertFalse(network.verify("node.bot-hosting.cloud"))
                response.read.return_value = json.dumps({"instance": network.probe_id}).encode()
                self.assertTrue(network.verify("node.bot-hosting.cloud"))
                self.assertFalse(network.verify("pretty.apps.bot-hosting.cloud"))
                self.assertEqual(factory.call_count, 2)

    def test_zero_variable_discovery_uses_verified_ipv4_and_persists(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"SERVER_IP": "0.0.0.0"}, clear=True):
            network = PublicNetwork(directory, 25476)
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = b"95.217.148.96\n"
            opener = Mock()
            opener.open.return_value = response
            with patch("hosting.network.urllib.request.build_opener", return_value=opener), patch.object(network, "verify", side_effect=lambda host: host == "95.217.148.96"):
                self.assertTrue(network.discover_once())
            self.assertEqual(network.host, "95.217.148.96")
            self.assertEqual(json.loads(network.path.read_text())["host"], network.host)
            self.assertEqual(PublicNetwork(directory, 25476).host, "", "Cached addresses must be reverified on restart")

    def test_no_address_published_when_verification_fails(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            network = PublicNetwork(directory, 25476)
            with patch.object(network, "verify", return_value=False), patch("hosting.network.urllib.request.build_opener") as factory:
                factory.return_value.open.side_effect = OSError("network unavailable")
                self.assertFalse(network.discover_once())
            self.assertEqual(network.host, "")

    def test_owner_origin_is_persisted_and_private_worker_is_preconfigured(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {}, clear=True):
            proxy = panel.Proxy(directory)
            proxy.network.observe_owner_origin("demo.apps.bot-hosting.cloud")
            restored = panel.Proxy(directory)
            self.assertEqual(restored.hosting_origin(), "https://demo.apps.bot-hosting.cloud")
            source = panel.standalone_worker(restored).decode()
            self.assertIn(restored.bridge["token"], source)
            self.assertIn('"UPSTREAM_ORIGIN": "https://demo.apps.bot-hosting.cloud"', source)
            self.assertIn("...BLUE_KNIGHT_CONFIG", source)
            self.assertFalse(restored.status()["network_ready"])
            self.assertEqual(restored.status()["tg_link"], "")

    def test_anonymous_requests_cannot_set_origin_but_owner_login_can(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory, patch.dict(panel.os.environ, {}, clear=True):
            proxy = panel.Proxy(directory)
            app = panel.App(proxy, hashlib.sha256(b"synthetic-password").hexdigest())
            server = panel.ThreadingHTTPServer(("127.0.0.1", 0), panel.handler_for(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, data=None):
                    connection = HTTPConnection("127.0.0.1", server.server_address[1])
                    connection.request("POST" if data else "GET", path, body=json.dumps(data) if data else None,
                                       headers={"Host": "demo.apps.bot-hosting.cloud", "Content-Type": "application/json"})
                    response = connection.getresponse()
                    status, headers = response.status, dict(response.getheaders())
                    response.read(); connection.close()
                    return status, headers
                request("/api/setup/status")
                self.assertEqual(proxy.network.origin, "")
                request("/api/login", {"password": "wrong"})
                self.assertEqual(proxy.network.origin, "")
                status, headers = request("/api/login", {"password": "synthetic-password"})
                self.assertEqual(status, 200)
                self.assertIn("Secure", headers["Set-Cookie"])
                self.assertEqual(proxy.network.origin, "https://demo.apps.bot-hosting.cloud")
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
