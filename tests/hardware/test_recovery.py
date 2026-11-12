import json
import os
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest
from conftest import RADIO_2G_SLOT, RADIO_5G_SLOT, REPO, Router, phys, say

BACKUPS = REPO / ".devshell" / "router-backups"
NVRAM = "/lib/firmware/brcm/brcmfmac4366c-pcie.asus,rt-ac86u.txt"
HOST_KEY = "dropbearkey -y -f /etc/dropbear/dropbear_ed25519_host_key | grep Fingerprint"
ROLLBACK_RULE = "hardware_test_rollback"
ROLLBACK_SECONDS = 30


def until(check, limit: float, interval: float = 2) -> bool:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(interval)
    return False


def attempt(router: Router, *options: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            router.ssh_args("true", *options), capture_output=True, text=True, timeout=15
        )
    except subprocess.TimeoutExpired as expired:
        return subprocess.CompletedProcess(expired.cmd, 255, "", "timed out")


def through(router: Router, lifeline: str, command: str) -> str:
    result = subprocess.run(
        router.ssh_args(command, "-S", lifeline), capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"{command} exited {result.returncode}: {result.stderr.strip()}"
    return result.stdout


def ubus(router: Router, path: str, method: str, lifeline: str, **arguments) -> str:
    return through(
        router, lifeline, f"ubus call {path} {method} {shlex.quote(json.dumps(arguments))}"
    )


def fresh_backup(router: Router) -> Path:
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = BACKUPS / f"{datetime.now():%Y%m%d-%H%M%S}-sysupgrade.tar.gz"
    with open(backup, "wb", opener=lambda path, flags: os.open(path, flags, 0o600)) as out:
        subprocess.run(router.ssh_args("sysupgrade -b -"), stdout=out, check=True, timeout=120)
    listing = subprocess.run(
        ["tar", "-tzf", str(backup)], capture_output=True, text=True, check=True
    )
    assert "etc/config/network" in listing.stdout.split(), f"{backup} holds no network settings"
    return backup


def reboot(router: Router, command: str = "reboot") -> None:
    router.ssh(f"(sleep 1; {command}) > /dev/null 2>&1 &")


@pytest.mark.disruptive
def test_unconfirmed_change_rolls_back_by_itself(router):
    before = router.run("uci export firewall")
    lifeline = str(REPO / ".devshell" / f"lifeline-{os.getpid()}")
    subprocess.run(
        router.ssh_args("true", "-M", "-S", lifeline, "-N", "-f"), check=True, timeout=30
    )
    session = json.loads(ubus(router, "session", "create", lifeline, timeout=300))[
        "ubus_rpc_session"
    ]
    try:
        ubus(
            router,
            "session",
            "grant",
            lifeline,
            ubus_rpc_session=session,
            scope="uci",
            objects=[["firewall", "read"], ["firewall", "write"]],
        )
        ubus(
            router,
            "uci",
            "add",
            lifeline,
            ubus_rpc_session=session,
            config="firewall",
            type="rule",
            name=ROLLBACK_RULE,
            values={
                "name": ROLLBACK_RULE,
                "src": "lan",
                "proto": "tcp",
                "dest_port": "22",
                "target": "REJECT",
            },
        )
        ubus(
            router,
            "uci",
            "apply",
            lifeline,
            ubus_rpc_session=session,
            rollback=True,
            timeout=ROLLBACK_SECONDS,
        )

        def live() -> bool:
            return ROLLBACK_RULE in through(router, lifeline, "nft list chain inet fw4 input_lan")

        assert until(live, 20, 1), "the change never reached the firewall"
        blocked = attempt(router)
        assert blocked.returncode == 255, f"a new SSH login still worked: {blocked.stdout}"
        assert until(lambda: attempt(router).returncode == 0, ROLLBACK_SECONDS + 60), (
            "access never came back"
        )
        assert router.run("uci export firewall") == before
    finally:
        if attempt(router).returncode != 0:
            subprocess.run(
                router.ssh_args(
                    f"uci -q delete firewall.{ROLLBACK_RULE}; uci commit firewall && fw4 reload",
                    "-S",
                    lifeline,
                ),
                check=True,
                timeout=60,
            )
        subprocess.run(
            router.ssh_args("true", "-S", lifeline, "-O", "exit"), check=True, timeout=30
        )


@pytest.mark.guided
def test_failsafe_boots_without_the_settings(router):
    settings = router.run("uci export")
    old = router.boot_id()
    failsafe = Router(router.host, "/dev/null")
    say(
        "After Enter the router reboots. Watch the power LED: from the moment it starts "
        "blinking, tap the LED button about twice a second for 10 seconds."
    )
    reboot(router)
    failsafe_boot = failsafe.wait_for_new_boot(old, limit=300)
    hostname = failsafe.run("cat /proc/sys/kernel/hostname").strip()
    assert hostname == "OpenWrt-failsafe", (
        f"booted as {hostname}: the press missed the window, run it again"
    )
    assert failsafe.run("cat /tmp/failsafe_button").strip() == "brightness_zero"
    root = failsafe.run("awk '$2 == \"/\" {print $3}' /proc/mounts").split()
    assert "squashfs" in root and "overlay" not in root, f"/ is mounted as {root}"
    reboot(failsafe, "reboot -f")
    router.wait_for_new_boot(failsafe_boot, limit=300)
    assert router.run("uci export") == settings


@pytest.mark.guided
@pytest.mark.destructive
def test_factory_reset_clears_settings_and_backup_restores_them(router):
    backup = fresh_backup(router)
    settings = router.run("uci export")
    shadow = router.run("sha256sum /etc/shadow").split()[0]
    host_key = router.run(HOST_KEY)
    old = router.boot_id()
    say(
        f"Settings are backed up to {backup}.\n"
        "If the WAN and LAN cables reach the same network, unplug WAN now.\n"
        "After Enter, hold Reset until the power LED blinks fast, about 5 s, then let go."
    )
    defaults = Router(router.host, "/dev/null")
    reset_boot = defaults.wait_for_new_boot(old, limit=420)
    try:
        assert defaults.run(HOST_KEY) != host_key, (
            "the host key survived, so the settings were not cleared"
        )
        assert defaults.run("sed -n 's/^root:\\([^:]*\\):.*/\\1/p' /etc/shadow").strip() == ""
        assert int(defaults.run(f"wc -c < {NVRAM}")) > 0
        assert set(phys(defaults)) == {RADIO_2G_SLOT, RADIO_5G_SLOT}
    finally:
        defaults.upload(backup, "/tmp/hardware-test-backup.tar.gz")
        defaults.run("sysupgrade -r /tmp/hardware-test-backup.tar.gz")
        reboot(defaults)
        router.wait_for_new_boot(reset_boot, limit=300)
    assert router.run("uci export") == settings, f"settings differ from the backup at {backup}"
    assert router.run("sha256sum /etc/shadow").split()[0] == shadow
    assert router.run(HOST_KEY) == host_key
    say("If you unplugged WAN, plug it back in now.")
