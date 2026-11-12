import hashlib
import socket
import struct
import threading

import pytest

from asus_rescue.cli import main
from asus_rescue.protocol import (
    RescueError,
    Timing,
    discovery_packet,
    flash,
    probe,
    write_packet,
)

FAST = Timing(
    discovery=3, request=3, resend=1, data_resend=0.5, settle=0, transfer=20, flash_idle=3
)


class FakeRouter(threading.Thread):
    def __init__(self, statuses: tuple[int, ...] = (3, 1), refuse_write: bool = False) -> None:
        super().__init__(daemon=True)
        self.statuses = statuses
        self.refuse_write = refuse_write
        self.control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.control.bind(("127.0.0.1", 0))
        self.control.settimeout(10)
        self.port = self.control.getsockname()[1]
        self.discovery = b""
        self.blocks: list[tuple[int, bytes]] = []

    def run(self) -> None:
        self.discovery, client = self.control.recvfrom(2048)
        self.control.sendto(struct.pack(">HH", 3, 1), client)
        request, client = self.control.recvfrom(2048)
        if request != write_packet():
            return
        if self.refuse_write:
            self.control.sendto(struct.pack(">HH", 5, 2) + b"Access violation\0", client)
            return
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transfer:
            transfer.bind(("127.0.0.1", 0))
            transfer.settimeout(10)
            transfer.sendto(struct.pack(">HH", 4, 0), client)
            while True:
                packet, client = transfer.recvfrom(2048)
                opcode, block = struct.unpack_from(">HH", packet)
                assert opcode == 3
                self.blocks.append((block, packet[4:]))
                transfer.sendto(struct.pack(">HH", 4, block), client)
                if len(packet) - 4 < 512:
                    break
            for status in self.statuses:
                transfer.sendto(struct.pack(">HH", 6, status), client)

    def image(self) -> bytes:
        return b"".join(payload for _, payload in self.blocks)


def run_flash(router: FakeRouter, image: bytes) -> None:
    router.start()
    flash(image, ("127.0.0.1", 0), "127.0.0.1", router.port, "127.0.0.1", FAST, lambda _: None)
    router.join(5)


def test_discovery_packet_matches_vendor_bytes() -> None:
    assert discovery_packet("192.168.1.1") == bytes.fromhex(
        "00014153555353504143454c494e4b0101a8c0006f6374657400"
    )


def test_write_packet_matches_vendor_bytes() -> None:
    assert write_packet() == bytes.fromhex("00024153555353504143454c494e4b006f6374657400")


def test_upload_delivers_every_byte_in_order() -> None:
    router = FakeRouter()
    image = bytes(range(256)) * 7
    run_flash(router, image)
    assert router.discovery == discovery_packet("127.0.0.1")
    assert [block for block, _ in router.blocks] == [1, 2, 3, 4]
    assert router.image() == image


def test_image_of_whole_blocks_ends_with_an_empty_block() -> None:
    router = FakeRouter()
    run_flash(router, b"\xaa" * 1024)
    assert [len(payload) for _, payload in router.blocks] == [512, 512, 0]


def test_router_rejection_is_a_failure() -> None:
    with pytest.raises(RescueError) as failure:
        run_flash(FakeRouter(statuses=(3, 2)), b"x" * 100)
    assert failure.value.kind == "flash_rejected"


def test_missing_flash_result_is_a_failure() -> None:
    with pytest.raises(RescueError) as failure:
        run_flash(FakeRouter(statuses=(3,)), b"x" * 100)
    assert failure.value.kind == "flash_timeout"


def test_router_error_is_named() -> None:
    with pytest.raises(RescueError) as failure:
        run_flash(FakeRouter(refuse_write=True), b"x" * 100)
    assert failure.value.kind == "server_error"
    assert "Access violation" in str(failure.value)


def test_wrong_checksum_sends_nothing(tmp_path) -> None:
    router = FakeRouter()
    image = tmp_path / "image.bin"
    image.write_bytes(b"firmware")
    code = main(
        [
            "flash",
            str(image),
            "--sha256",
            "0" * 64,
            "--source",
            "127.0.0.1",
            "--router",
            "127.0.0.1",
            "--port",
            str(router.port),
            "--unicast-discovery",
        ]
    )
    assert code == 1
    router.control.settimeout(0.3)
    with pytest.raises(TimeoutError):
        router.control.recvfrom(2048)


def test_cli_flashes_a_verified_image(tmp_path) -> None:
    router = FakeRouter()
    router.start()
    image = tmp_path / "image.bin"
    image.write_bytes(b"y" * 700)
    code = main(
        [
            "flash",
            str(image),
            "--sha256",
            hashlib.sha256(b"y" * 700).hexdigest(),
            "--source",
            "127.0.0.1",
            "--router",
            "127.0.0.1",
            "--port",
            str(router.port),
            "--unicast-discovery",
        ],
        timing=FAST,
    )
    router.join(5)
    assert code == 0
    assert router.image() == b"y" * 700


def test_probe_discovers_and_requests_no_upload() -> None:
    responder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    responder.bind(("127.0.0.1", 0))
    responder.settimeout(5)
    seen: list[bytes] = []

    def answer() -> None:
        packet, client = responder.recvfrom(2048)
        seen.append(packet)
        responder.sendto(struct.pack(">HH", 3, 1), client)

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    code = main(
        [
            "probe",
            "--source",
            "127.0.0.1",
            "--router",
            "127.0.0.1",
            "--port",
            str(responder.getsockname()[1]),
            "--unicast-discovery",
        ],
        timing=FAST,
    )
    thread.join(5)
    assert code == 0
    assert seen == [discovery_packet("127.0.0.1")]
    responder.settimeout(0.3)
    with pytest.raises(TimeoutError):
        responder.recvfrom(2048)
    responder.close()


def test_probe_without_router_fails() -> None:
    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind(("127.0.0.1", 0))
    quick = Timing(discovery=0.5, resend=0.2, settle=0)
    port = str(silent.getsockname()[1])
    args = ["probe", "--source", "127.0.0.1", "--router", "127.0.0.1", "--port", port]
    assert main([*args, "--unicast-discovery"], timing=quick) == 1
    silent.close()


def test_unexpected_reply_is_reported_not_dropped() -> None:
    responder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    responder.bind(("127.0.0.1", 0))
    responder.settimeout(5)

    def answer_from_another_port() -> None:
        _, client = responder.recvfrom(2048)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
            other.sendto(struct.pack(">HH", 3, 1), client)

    thread = threading.Thread(target=answer_from_another_port, daemon=True)
    thread.start()
    lines: list[str] = []
    quick = Timing(discovery=1, resend=5, settle=0)
    with pytest.raises(RescueError):
        probe(
            ("127.0.0.1", 0),
            "127.0.0.1",
            responder.getsockname()[1],
            "127.0.0.1",
            quick,
            lines.append,
        )
    thread.join(5)
    responder.close()
    assert any(line.startswith("ignored 4 bytes from 127.0.0.1:") for line in lines)
    assert any(line.endswith(": 00030001") for line in lines)


def test_fixed_local_port_is_the_one_the_router_sees() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as free:
        free.bind(("127.0.0.1", 0))
        local_port = free.getsockname()[1]
    responder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    responder.bind(("127.0.0.1", 0))
    responder.settimeout(5)
    clients: list[tuple[str, int]] = []

    def answer() -> None:
        _, client = responder.recvfrom(2048)
        clients.append(client)
        responder.sendto(struct.pack(">HH", 3, 1), client)

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    code = main(
        [
            "probe",
            "--source",
            "127.0.0.1",
            "--local-port",
            str(local_port),
            "--router",
            "127.0.0.1",
            "--port",
            str(responder.getsockname()[1]),
            "--unicast-discovery",
        ],
        timing=FAST,
    )
    thread.join(5)
    responder.close()
    assert code == 0
    assert clients == [("127.0.0.1", local_port)]
