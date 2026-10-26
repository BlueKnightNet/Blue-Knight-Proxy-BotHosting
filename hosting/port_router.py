"""Share one allocated TCP port between HTTP and FakeTLS MTProto."""
import asyncio
import ipaddress

HTTP_PREFIXES = (b"GET ", b"POST", b"HEAD", b"DELE", b"PUT ", b"OPTI", b"PATC")


class PortRouter:
    def __init__(self, http_port, proxy_port, limit=128, proxy_protocol=False):
        self.http_port = http_port
        self.proxy_port = proxy_port
        self.limit = limit
        self.active = 0
        self.proxy_protocol = proxy_protocol

    async def pipe(self, reader, writer):
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), 300)
            if not chunk:
                if writer.can_write_eof():
                    writer.write_eof()
                    await writer.drain()
                return
            writer.write(chunk)
            await writer.drain()

    async def handle(self, reader, writer):
        if self.active >= self.limit:
            writer.close()
            return
        self.active += 1
        upstream = None
        tasks = []
        try:
            prefix = await asyncio.wait_for(reader.readexactly(4), 10)
            port = self.http_port if prefix in HTTP_PREFIXES else self.proxy_port
            upstream_reader, upstream = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 5)
            if port == self.proxy_port and self.proxy_protocol:
                peer, local = writer.get_extra_info("peername"), writer.get_extra_info("sockname")
                family = "TCP4" if ipaddress.ip_address(peer[0]).version == 4 else "TCP6"
                upstream.write(f"PROXY {family} {peer[0]} {local[0]} {peer[1]} {local[1]}\r\n".encode("ascii"))
            upstream.write(prefix)
            await upstream.drain()
            tasks = [asyncio.create_task(self.pipe(reader, upstream)), asyncio.create_task(self.pipe(upstream_reader, writer))]
            await asyncio.gather(*tasks)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            for connection in (upstream, writer):
                if connection:
                    connection.close()
            self.active -= 1
