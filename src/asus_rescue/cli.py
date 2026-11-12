import argparse
import hashlib
import ipaddress
import re
import sys
from pathlib import Path

from asus_rescue import __version__
from asus_rescue.protocol import RescueError, Timing, flash, flash_idle_seconds, probe

SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")


def _ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not an IPv4 address: {value}") from error


def _sha256(value: str) -> str:
    if not SHA256_HEX.fullmatch(value):
        raise argparse.ArgumentTypeError("expected 64 hexadecimal characters")
    return value.lower()


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port out of range: {port}")
    return port


def _local_port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port out of range: {port}")
    return port


def parser() -> argparse.ArgumentParser:
    network = argparse.ArgumentParser(add_help=False)
    network.add_argument("--source", type=_ipv4, default="192.168.1.10", help="local address")
    network.add_argument("--router", type=_ipv4, default="192.168.1.1", help="rescue address")
    network.add_argument("--port", type=_port, default=69, help="rescue UDP port")
    network.add_argument(
        "--local-port",
        type=_local_port,
        default=0,
        help="fixed local UDP port to open in a host firewall; 0 picks any",
    )
    network.add_argument(
        "--unicast-discovery",
        action="store_true",
        help="send discovery to the router address instead of broadcast",
    )
    result = argparse.ArgumentParser(
        prog="asus-rescue",
        description="Talk to an ASUS router in rescue mode over its LAN port.",
    )
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "probe", parents=[network], help="find the router in rescue mode; writes nothing"
    )
    flash_command = commands.add_parser(
        "flash", parents=[network], help="upload an image and wait for the flash result"
    )
    flash_command.add_argument("image", type=Path, help="firmware image to upload")
    flash_command.add_argument(
        "--sha256", type=_sha256, required=True, help="SHA256 the image must have"
    )
    flash_command.add_argument(
        "--dry-run", action="store_true", help="verify the image and print the plan only"
    )
    return result


def _report(line: str) -> None:
    print(line, file=sys.stderr)


def main(argv: list[str] | None = None, timing: Timing | None = None) -> int:
    args = parser().parse_args(argv)
    target = args.router if args.unicast_discovery else "255.255.255.255"
    source = (args.source, args.local_port)
    if args.command == "probe":
        try:
            probe(source, args.router, args.port, target, timing or Timing(), _report)
        except RescueError as error:
            print(f"{error.kind}: {error}", file=sys.stderr)
            return 1
        print(f"router at {args.router} is in rescue mode and accepts uploads", file=sys.stderr)
        return 0
    try:
        image = args.image.read_bytes()
    except OSError as error:
        print(f"local_file: {args.image}: {error.strerror}", file=sys.stderr)
        return 1
    actual = hashlib.sha256(image).hexdigest()
    if actual != args.sha256:
        print(
            f"image_mismatch: {args.image} has SHA256 {actual}, expected {args.sha256}; "
            "no packet was sent",
            file=sys.stderr,
        )
        return 1
    print(
        f"image {args.image} ({len(image)} bytes, SHA256 verified), "
        f"{args.source}:{args.local_port} -> {args.router}:{args.port}, discovery via {target}, "
        f"flash wait {flash_idle_seconds(len(image)):g}s",
        file=sys.stderr,
    )
    if args.dry_run:
        return 0
    try:
        flash(
            image,
            source,
            args.router,
            args.port,
            target,
            timing or Timing(),
            _report,
        )
    except RescueError as error:
        print(f"{error.kind}: {error}", file=sys.stderr)
        return 1
    print("router reports the flash succeeded; it reboots on its own", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
