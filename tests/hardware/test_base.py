import json
import os
import re

from conftest import BOARD

KERNEL_ERRORS = (
    r" Oops:",
    r"\bBUG:",
    r"Kernel panic",
    r"Out of memory",
    r"SQUASHFS error",
    r"UBIFS error",
    r"EXT4-fs error",
    r"Buffer I/O error",
    r"Call trace:",
    r"Dongle setup failed",
    r"dongle is not responding",
)


def test_board_is_the_rt_ac86u(router):
    board = json.loads(router.run("ubus call system board"))
    assert board["board_name"] == BOARD
    assert board["release"]["distribution"] == "OpenWrt"


def test_firmware_comes_from_the_pinned_openwrt(router):
    expected = os.environ.get("EXPECTED_OPENWRT_REV", "")
    running = router.run("cat /etc/openwrt_version").strip()
    assert expected, "EXPECTED_OPENWRT_REV is not set; the runner reads it from flake.lock"
    assert expected.startswith(running), f"running {running}, pinned {expected}"


def test_kernel_log_has_no_errors(router):
    log = router.dmesg()
    found = [line for line in log.splitlines() if any(re.search(p, line) for p in KERNEL_ERRORS)]
    assert not found, "\n".join(found)


def test_core_services_run(router):
    running = router.run("ubus call service list")
    services = json.loads(running)
    for name in ("dropbear", "rpcd", "network", "log", "dnsmasq"):
        instances = services.get(name, {}).get("instances", {})
        assert any(i.get("running") for i in instances.values()), f"{name} is not running"


def test_firewall_tables_are_loaded(router):
    assert "chain input" in router.run("nft list table inet fw4")


def test_overlay_is_writable(router):
    mounts = router.run("cat /proc/mounts")
    overlay = [line for line in mounts.splitlines() if " /overlay " in line]
    assert overlay and "tmpfs" not in overlay[0], f"overlay is {overlay}"
    marker = "/etc/.hardware-test-marker"
    router.run(f"echo written > {marker}")
    assert router.run(f"cat {marker} && rm {marker}").strip() == "written"
