import json
import os
import re

import pytest


def first_time(log: str, pattern: str) -> float:
    match = re.search(rf"\[\s*([0-9.]+)\][^\n]*{pattern}", log)
    assert match, f"{pattern!r} not in the kernel log"
    return float(match.group(1))


def test_watchdog_exists_before_the_switch_probes(router):
    log = router.dmesg()
    assert first_time(log, "Registered BCM7038 Watchdog") < first_time(log, "found switch")


def test_switch_is_reset_once_per_boot(router):
    assert len(re.findall(r"found switch: BCM4908", router.dmesg())) == 1


def test_procd_pets_the_watchdog(router):
    status = json.loads(router.run("ubus call system watchdog"))
    assert status["status"] == "running"


def test_lockups_end_in_a_panic(router):
    for name in ("softlockup_panic", "hardlockup_panic", "hung_task_panic"):
        assert router.sysfs(f"/proc/sys/kernel/{name}") == "1", name
    assert int(router.sysfs("/proc/sys/kernel/panic")) > 0


def test_panic_records_go_to_misc3(router):
    log = router.dmesg()
    misc3 = router.run("grep '\"misc3\"' /proc/mtd").split(":")[0]
    assert re.search(rf"mtd {misc3}: mtdoops-pstore: Attached to MTD device", log)
    assert " /sys/fs/pstore " in router.run("cat /proc/mounts")


def test_hardware_rng_feeds_the_kernel(router):
    assert router.sysfs("/sys/class/misc/hw_random/rng_current").startswith("iproc-rng200")


@pytest.mark.destructive
def test_a_panic_reboots_and_leaves_a_record(router):
    old = router.boot_id()
    marker = f"hardware-test-panic {old}"
    router.ssh(
        f"sync; echo '{marker}' > /dev/kmsg; echo 1 > /proc/sys/kernel/sysrq; "
        "(sleep 1; echo c > /proc/sysrq-trigger) > /dev/null 2>&1 &"
    )
    router.wait_for_new_boot(old, limit=240)
    holding = router.run(f"grep -l '{marker}' /sys/fs/pstore/* 2>/dev/null; true").split()
    assert holding, f"no record in /sys/fs/pstore holds {marker!r}"
    router.run("rm " + " ".join(holding))


@pytest.mark.destructive
def test_reboots_come_back(router):
    count = int(os.environ.get("ROUTER_REBOOTS", "5"))
    kept = set(router.run("ls /sys/fs/pstore").split())
    for boot in range(1, count + 1):
        old = router.boot_id()
        router.ssh("(sleep 1; reboot) > /dev/null 2>&1 &")
        router.wait_for_new_boot(old, limit=300)
        log = router.dmesg()
        assert len(re.findall(r"brcmf_c_preinit_dcmds: Firmware", log)) == 2
        crashed = sorted(set(router.run("ls /sys/fs/pstore").split()) - kept)
        where = (
            router.run(f"cd /sys/fs/pstore && grep -ah -m 1 'pc : ' {' '.join(crashed)}; true")
            if crashed
            else ""
        )
        assert not crashed, f"boot {boot} crashed on the way up, left {crashed}: {where.strip()}"
