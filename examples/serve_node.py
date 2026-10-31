#!/usr/bin/env python3
"""iroh <-> TCP forwarder: run an iroh node on the Windows 7 machine.

Deployment example for iroh-win7. One script, three modes:

  serve [host] [port]      accept iroh streams, proxy each into host:port
                           (default 127.0.0.1:22 -- a local sshd)
  forward <id> [port]      listen on 127.0.0.1:port and proxy each TCP
                           connection over iroh to endpoint <id> (manual tunnel)
  stdio <id>               proxy stdin/stdout over iroh -- the ssh ProxyCommand
                           mode: no daemon, lives only for the session

Transport is a self-hosted iroh relay: both endpoints register there by
endpoint id, then usually hole-punch into a direct path (the relay remains as
fallback). Both sides must use the same ALPN (IROH_ALPN, default
iroh-ssh-fwd/0).

Environment:
  IROH_RELAY_URL        relay URL        (default https://iroh.example.com:4443)
  IROH_RELAY_QUIC_PORT  relay QUIC port  (default 7842)
  IROH_RELAY_TOKEN      relay auth token; otherwise read from
                        ~/.config/iroh-ssh/token

Identity: ~/.config/iroh-ssh/secret.key, 32 random bytes minted on first run.
The endpoint id derives from this file: back it up, never copy it to a second
machine (a duplicated id means both instances race for incoming connections).

Requires the iroh-win7 wheel (or the official PyPI wheel on modern Windows);
make sure the directory containing the `iroh` package is on sys.path, e.g.:
  set PYTHONPATH=C:\iroh7\site
"""
import asyncio, contextlib, os, sys, pathlib
import iroh

ALPN = os.environ.get("IROH_ALPN", "iroh-ssh-fwd/0").encode()
CFG = pathlib.Path(os.path.expanduser("~/.config/iroh-ssh"))
BUF = 65536
DEBUG = os.environ.get("IROHSSH_DEBUG") == "1"

RELAY_URL = os.environ.get("IROH_RELAY_URL", "https://iroh.example.com:4443")
RELAY_QUIC = int(os.environ.get("IROH_RELAY_QUIC_PORT", "7842"))


def log(msg):
    # never stdout: in stdio mode that channel carries ssh traffic
    print(msg, file=sys.stderr, flush=True)


def relay_token():
    tok = os.environ.get("IROH_RELAY_TOKEN")
    if tok:
        return tok.strip()
    f = CFG / "token"
    if f.exists():
        return f.read_text().strip()
    sys.exit("no relay token: set IROH_RELAY_TOKEN or write ~/.config/iroh-ssh/token")


def relay_mode():
    m = iroh.RelayMap.empty()
    m.insert(iroh.RelayConfig(url=RELAY_URL, quic_port=RELAY_QUIC, auth_token=relay_token()))
    return iroh.RelayMode.custom(m)


def secret_key():
    """Persist the key so the endpoint id is stable across restarts."""
    CFG.mkdir(parents=True, exist_ok=True)
    f = CFG / "secret.key"
    if not f.exists():
        f.write_bytes(os.urandom(32))
        f.chmod(0o600)
    return f.read_bytes()


def remote_addr(remote_id):
    return iroh.EndpointAddr(iroh.EndpointId.from_string(remote_id), RELAY_URL, [])


async def pump_tcp_to_iroh(reader, send):
    try:
        while True:
            data = await reader.read(BUF)
            if not data:
                break
            await send.write_all(data)
    except Exception as e:
        if DEBUG:
            log(f"pump out: {e!r}")
    finally:
        with contextlib.suppress(Exception):
            await send.finish()


async def pump_iroh_to_tcp(recv, writer):
    try:
        while True:
            data = await recv.read(BUF)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception as e:
        if DEBUG:
            log(f"pump in: {e!r}")
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def splice(bi, reader, writer):
    send, recv = bi.send(), bi.recv()   # methods, not attributes
    await asyncio.gather(
        pump_tcp_to_iroh(reader, send),
        pump_iroh_to_tcp(recv, writer),
    )


async def serve(target_host, target_port):
    ep = await iroh.Endpoint.bind(iroh.EndpointOptions(
        secret_key=secret_key(), alpns=[ALPN], relay_mode=relay_mode()))
    await ep.online()
    log(f"endpoint id: {ep.id()}")
    log(f"relay {RELAY_URL} -> {target_host}:{target_port}")

    async def one_conn(inc):
        try:
            conn = await (await inc.accept()).connect()
            log(f"conn from {conn.remote_id()}")
            while True:
                bi = await conn.accept_bi()
                r, w = await asyncio.open_connection(target_host, target_port)
                asyncio.create_task(splice(bi, r, w))
        except Exception as e:
            if DEBUG:
                log(f"conn closed: {e!r}")

    while True:
        inc = await ep.accept_next()
        if inc is None:
            break
        asyncio.create_task(one_conn(inc))


async def dial(remote_id):
    ep = await iroh.Endpoint.bind(iroh.EndpointOptions(alpns=[ALPN], relay_mode=relay_mode()))
    await ep.online()
    return await ep.connect(remote_addr(remote_id), ALPN), ep


async def forward(remote_id, bind_host, bind_port):
    ep = await iroh.Endpoint.bind(iroh.EndpointOptions(alpns=[ALPN], relay_mode=relay_mode()))
    await ep.online()
    addr = remote_addr(remote_id)

    async def handle(reader, writer):
        try:
            conn = await ep.connect(addr, ALPN)
            await splice(await conn.open_bi(), reader, writer)
        except Exception as e:
            log(f"forward failed: {e!r}")
            with contextlib.suppress(Exception):
                writer.close()

    srv = await asyncio.start_server(handle, bind_host, bind_port)
    log(f"listening {bind_host}:{bind_port} -> {remote_id[:16]}... via {RELAY_URL}")
    async with srv:
        await srv.serve_forever()


class _ThreadReader:
    """Windows has no connect_read_pipe: park the blocking read in a worker thread."""

    def __init__(self, f):
        self._f = f

    async def read(self, n):
        return await asyncio.to_thread(self._f.read1, n)


class _ThreadWriter:
    def __init__(self, f):
        self._f = f
        self._buf = b""

    def write(self, data):
        self._buf += data

    async def drain(self):
        data, self._buf = self._buf, b""
        if data:
            await asyncio.to_thread(self._flush, data)

    def _flush(self, data):
        self._f.write(data)
        self._f.flush()

    def close(self):
        with contextlib.suppress(Exception):
            self._f.flush()


async def stdio_pipes():
    if os.name == "nt":
        return _ThreadReader(sys.stdin.buffer), _ThreadWriter(sys.stdout.buffer)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    transport, proto = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout.buffer)
    return reader, asyncio.StreamWriter(transport, proto, reader, loop)


async def stdio(remote_id):
    """ssh ProxyCommand mode: no daemon, lives only for this session."""
    reader, writer = await stdio_pipes()
    conn, _ep = await dial(remote_id)
    try:
        await splice(await conn.open_bi(), reader, writer)
    finally:
        if os.name == "nt":
            # a stdin read may still be parked in a worker thread; don't let it hold up exit
            with contextlib.suppress(Exception):
                sys.stdout.buffer.flush()
            os._exit(0)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "serve":
        host = rest[0] if rest else "127.0.0.1"
        port = int(rest[1]) if len(rest) > 1 else 22
        asyncio.run(serve(host, port))
    elif cmd == "forward":
        if not rest:
            sys.exit("usage: forward <endpoint-id> [local-port]")
        asyncio.run(forward(rest[0], "127.0.0.1", int(rest[1]) if len(rest) > 1 else 2222))
    elif cmd == "stdio":
        if not rest:
            sys.exit("usage: stdio <endpoint-id>")
        asyncio.run(stdio(rest[0]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
