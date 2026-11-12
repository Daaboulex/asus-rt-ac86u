import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOST = os.environ.get("ROUTER", "")
KNOWN_HOSTS = os.environ.get("ROUTER_KNOWN_HOSTS", str(REPO / ".devshell" / "router_known_hosts"))
GUIDED = os.environ.get("ROUTER_GUIDED") == "1"
DISRUPTIVE = os.environ.get("ROUTER_DISRUPTIVE") == "1"
DESTRUCTIVE = os.environ.get("ROUTER_DESTRUCTIVE") == "1"

BOARD = "asus,rt-ac86u"
RADIO_2G_SLOT = "0000:01:00.0"
RADIO_5G_SLOT = "0001:01:00.0"
LEDS = (
    "white:power",
    "white:lan-1",
    "white:lan-2",
    "white:lan-3",
    "white:lan-4",
    "white:wan",
    "red:wan",
    "brcmfmac-phy0",
    "brcmfmac-phy1",
)
SWITCH_PORTS = ("lan1", "lan2", "lan3", "lan4", "wan")


class RouterUnreachable(RuntimeError):
    pass


@dataclass
class Router:
    host: str
    known_hosts: str

    def ssh_args(self, command: str, *options: str) -> list[str]:
        return [
            "ssh",
            "-F",
            "/dev/null",
            "-o",
            f"UserKnownHostsFile={self.known_hosts}",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "LogLevel=ERROR",
            *options,
            f"root@{self.host}",
            command,
        ]

    def ssh(self, command: str, timeout: int = 120) -> subprocess.CompletedProcess:
        args = self.ssh_args(command)
        for _ in range(6):
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 255:
                return result
            time.sleep(2)
        raise RouterUnreachable(f"{self.host}: {result.stderr.strip()}")

    def run(self, command: str, timeout: int = 120) -> str:
        result = self.ssh(command, timeout)
        if result.returncode != 0:
            raise AssertionError(f"{command!r} exited {result.returncode}: {result.stderr.strip()}")
        return result.stdout

    def upload(self, local: Path, remote: str) -> None:
        with local.open("rb") as data:
            result = subprocess.run(
                self.ssh_args(f"cat > {remote}"),
                stdin=data,
                capture_output=True,
                timeout=300,
            )
        if result.returncode != 0:
            raise AssertionError(f"upload of {local} failed: {result.stderr.decode().strip()}")

    def dmesg(self) -> str:
        return self.run("dmesg")

    def boot_id(self) -> str:
        return self.run("cat /proc/sys/kernel/random/boot_id").strip()

    def wait_for_new_boot(self, old: str, limit: int) -> str:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            time.sleep(5)
            try:
                result = self.ssh("cat /proc/sys/kernel/random/boot_id", timeout=15)
            except (RouterUnreachable, subprocess.TimeoutExpired):
                continue
            current = result.stdout.strip()
            if result.returncode == 0 and current and current != old:
                return current
        raise AssertionError(f"no new boot within {limit} s")

    def sysfs(self, path: str) -> str:
        return self.run(f"cat {path}").strip()

    def led(self, name: str) -> tuple[int, str]:
        brightness = int(self.sysfs(f"/sys/class/leds/{name}/brightness"))
        triggers = self.sysfs(f"/sys/class/leds/{name}/trigger")
        active = re.search(r"\[([^\]]+)\]", triggers)
        return brightness, active.group(1) if active else ""


def phys(router: Router) -> dict[str, str]:
    listing = router.run(
        "for p in /sys/class/ieee80211/*; do "
        'echo "${p##*/} $(basename $(readlink -f $p/device))"; done'
    )
    return {slot: phy for phy, slot in (line.split() for line in listing.splitlines())}


def radio_section(router: Router, slot: str) -> str:
    sections = router.run("uci show wireless")
    match = re.search(rf"^wireless\.([^.]+)\.path='[^']*{re.escape(slot)}'$", sections, re.M)
    assert match, f"no wireless section names {slot}"
    return match.group(1)


def prompt(text: str) -> str:
    with open("/dev/tty", "w") as out, open("/dev/tty") as answer:
        out.write(text)
        out.flush()
        return answer.readline()


def ask(question: str) -> bool:
    return prompt(f"\n{question} [y/n] ").strip().lower().startswith("y")


def say(instruction: str) -> None:
    prompt(f"\n{instruction}\nPress Enter when ready. ")


@pytest.fixture(scope="session")
def router() -> Router:
    if not HOST:
        pytest.skip("ROUTER is not set; hardware tests need a router to talk to")
    return Router(HOST, KNOWN_HOSTS)


def pytest_collection_modifyitems(config, items):
    gates = {
        "guided": (GUIDED, "set ROUTER_GUIDED=1 to run the steps that need hands and eyes"),
        "disruptive": (DISRUPTIVE, "set ROUTER_DISRUPTIVE=1 to allow brief outages"),
        "destructive": (DESTRUCTIVE, "set ROUTER_DESTRUCTIVE=1 to allow crashes and reflashing"),
    }
    for item in items:
        for name, (enabled, reason) in gates.items():
            if name in item.keywords and not enabled:
                item.add_marker(pytest.mark.skip(reason=reason))


def pytest_configure(config):
    for name in ("guided", "disruptive", "destructive"):
        config.addinivalue_line("markers", f"{name}: hardware test gated by ROUTER_{name.upper()}")
