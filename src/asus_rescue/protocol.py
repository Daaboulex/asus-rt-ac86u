import socket
import struct
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

MAGIC = b"ASUSSPACELINK"
BLOCK_SIZE = 512
OP_DISCOVER = 1
OP_WRITE = 2
OP_DATA = 3
OP_ACK = 4
OP_ERROR = 5
OP_STATUS = 6
STATUS_DONE = 1
STATUS_WRITING = 3
MEBIBYTE = 1048576


class RescueError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Timing:
    discovery: float = 31.0
    request: float = 11.0
    resend: float = 5.0
    data_resend: float = 2.0
    data_attempts: int = 6
    settle: float = 2.0
    transfer: float = 600.0
    flash_idle: float | None = None


def discovery_packet(router: str) -> bytes:
    packet = bytearray(26)
    packet[1] = OP_DISCOVER
    packet[2:15] = MAGIC
    packet[15:19] = socket.inet_aton(router)[::-1]
    packet[20:25] = b"octet"
    return bytes(packet)


def write_packet() -> bytes:
    packet = bytearray(22)
    packet[1] = OP_WRITE
    packet[2:15] = MAGIC
    packet[16:21] = b"octet"
    return bytes(packet)


def data_packet(block: int, payload: bytes) -> bytes:
    if len(payload) > BLOCK_SIZE:
        raise ValueError(f"a data block carries at most {BLOCK_SIZE} bytes")
    return struct.pack(">HH", OP_DATA, block) + payload


def flash_idle_seconds(size: int) -> float:
    return 450.0 + 24.0 * (size // MEBIBYTE)


def _header(packet: bytes) -> tuple[int, int] | None:
    if len(packet) < 4:
        return None
    return struct.unpack_from(">HH", packet)


def _receive(sock: socket.socket, until: float) -> tuple[bytes, tuple[str, int]] | None:
    sock.settimeout(max(0.01, min(0.1, until - time.monotonic())))
    try:
        return sock.recvfrom(2048)
    except TimeoutError:
        return None


def _router_error(packet: bytes) -> RescueError:
    text = packet[4:260].rstrip(b"\0").decode("ascii", "replace")
    return RescueError("server_error", f"router error {_header(packet)[1]}: {text}")


class Session:
    def __init__(
        self,
        sock: socket.socket,
        router: str,
        port: int,
        timing: Timing,
        report: Callable[[str], None],
    ) -> None:
        self.sock = sock
        self.router = router
        self.port = port
        self.timing = timing
        self.report = report
        self.transfer_deadline = time.monotonic() + timing.transfer

    def exchange(
        self,
        request: bytes,
        destination: tuple[str, int],
        expected_port: int | None,
        reply: tuple[int, int],
        resend: float,
        timeout: float,
        kind: str,
    ) -> tuple[str, int]:
        until = min(time.monotonic() + timeout, self.transfer_deadline)
        next_send = 0.0
        while time.monotonic() < until:
            if time.monotonic() >= next_send:
                self.sock.sendto(request, destination)
                next_send = time.monotonic() + resend
            received = _receive(self.sock, until)
            if received is None:
                continue
            packet, sender = received
            header = _header(packet)
            if sender[0] == self.router and expected_port in (None, sender[1]):
                if header is not None and header[0] == OP_ERROR:
                    raise _router_error(packet)
                if header == reply:
                    return sender
            self.report(
                f"ignored {len(packet)} bytes from {sender[0]}:{sender[1]}: {packet[:32].hex()}"
            )
        raise RescueError(kind, f"no reply {reply} from {self.router} within {timeout:g}s")

    def discover(self, target: str) -> None:
        self.report(f"discovering {self.router} via {target}:{self.port}")
        self.exchange(
            discovery_packet(self.router),
            (target, self.port),
            self.port,
            (OP_DATA, 1),
            self.timing.resend,
            self.timing.discovery,
            "discovery_timeout",
        )
        time.sleep(self.timing.settle)

    def request_write(self) -> tuple[str, int]:
        self.report("router found, requesting upload")
        return self.exchange(
            write_packet(),
            (self.router, self.port),
            None,
            (OP_ACK, 0),
            self.timing.resend,
            self.timing.request,
            "request_timeout",
        )

    def send(self, peer: tuple[str, int], image: bytes) -> None:
        block = 1
        offset = 0
        step = max(1, len(image) // BLOCK_SIZE // 10)
        while True:
            payload = image[offset : offset + BLOCK_SIZE]
            self.exchange(
                data_packet(block, payload),
                peer,
                peer[1],
                (OP_ACK, block),
                self.timing.data_resend,
                self.timing.data_resend * self.timing.data_attempts,
                "transfer_timeout",
            )
            offset += len(payload)
            if (offset // BLOCK_SIZE) % step == 0:
                self.report(f"uploaded {offset} of {len(image)} bytes")
            if len(payload) < BLOCK_SIZE:
                return
            block = (block + 1) & 0xFFFF

    def await_flash(self, peer: tuple[str, int], size: int) -> None:
        idle = self.timing.flash_idle or flash_idle_seconds(size)
        absolute = time.monotonic() + max(1800.0, idle * 3)
        deadline = time.monotonic() + idle
        self.report("upload complete, router is writing flash, keep power connected")
        while time.monotonic() < min(deadline, absolute):
            received = _receive(self.sock, min(deadline, absolute))
            if received is None:
                continue
            packet, sender = received
            header = _header(packet)
            if sender != peer or header is None:
                continue
            if header[0] == OP_ERROR:
                raise _router_error(packet)
            if header[0] != OP_STATUS or (len(packet) > 4 and packet[2] != 0):
                continue
            if header[1] == STATUS_DONE:
                return
            if header[1] != STATUS_WRITING:
                raise RescueError(
                    "flash_rejected", f"router rejected the image, status {header[1]}"
                )
            deadline = time.monotonic() + idle
        raise RescueError(
            "flash_timeout", "upload finished but the router reported no flash result"
        )


@contextmanager
def _bound(source: tuple[str, int]) -> Iterator[socket.socket]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind(source)
        except OSError as error:
            raise RescueError(
                "network", f"cannot bind {source[0]}:{source[1]}: {error.strerror}"
            ) from error
        yield sock


def probe(
    source: tuple[str, int],
    router: str,
    port: int,
    discovery_target: str,
    timing: Timing,
    report: Callable[[str], None],
) -> None:
    with _bound(source) as sock:
        Session(sock, router, port, timing, report).discover(discovery_target)


def flash(
    image: bytes,
    source: tuple[str, int],
    router: str,
    port: int,
    discovery_target: str,
    timing: Timing,
    report: Callable[[str], None],
) -> None:
    if not image:
        raise RescueError("invalid_input", "the firmware image is empty")
    with _bound(source) as sock:
        session = Session(sock, router, port, timing, report)
        session.discover(discovery_target)
        peer = session.request_write()
        session.send(peer, image)
        session.await_flash(peer, len(image))
