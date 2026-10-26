import asyncio
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hosting.port_router import PortRouter


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servers = []
        self.received = []
        async def backend(tag, reader, writer):
            data = await reader.read()
            self.received.append((tag, data))
            writer.write(tag + data)
            await writer.drain()
            writer.close()
        self.http = await asyncio.start_server(lambda r, w: backend(b"HTTP:", r, w), "127.0.0.1", 0)
        self.proxy = await asyncio.start_server(lambda r, w: backend(b"TCP:", r, w), "127.0.0.1", 0)
        self.router = PortRouter(self.http.sockets[0].getsockname()[1], self.proxy.sockets[0].getsockname()[1])
        self.server = await asyncio.start_server(self.router.handle, "127.0.0.1", 0)
        self.servers = [self.http, self.proxy, self.server]
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        for server in self.servers:
            server.close()
            await server.wait_closed()

    async def exchange(self, body, fragments=False):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        if fragments:
            writer.write(body[:1]); await writer.drain()
            await asyncio.sleep(0.01)
            writer.write(body[1:])
        else:
            writer.write(body)
        await writer.drain()
        writer.write_eof()
        result = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        await writer.wait_closed()
        return result

    async def test_fragmented_http_and_half_close(self):
        request = b"GET /health HTTP/1.1\r\nHost: example\r\n\r\n"
        self.assertEqual(await self.exchange(request, fragments=True), b"HTTP:" + request)

    async def test_binary_large_payload_is_forwarded_without_truncation(self):
        payload = b"\x16\x03\x01\x00" + bytes(range(256)) * 1024
        self.assertEqual(await self.exchange(payload), b"TCP:" + payload)

    async def test_client_ip_header_precedes_native_bytes(self):
        self.router.proxy_protocol = True
        payload = b"\x16\x03\x01\x00hello"
        result = await self.exchange(payload)
        self.assertTrue(result.startswith(b"TCP:PROXY TCP4 127.0.0.1 127.0.0.1 "))
        self.assertTrue(result.endswith(b"\r\n" + payload))

    async def test_connection_cap_closes_without_opening_backend(self):
        self.router.limit = 0
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.received, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
