import re

import pytest
from conftest import say


def usb_disks(router) -> dict[str, str]:
    listing = router.run(
        "for d in /sys/block/sd*; do [ -e $d ] || continue; "
        'echo "${d##*/} $(readlink -f $d/device)"; done'
    )
    return dict(line.split() for line in listing.splitlines())


def port_speed(router, path: str) -> str:
    usb = re.search(r"(/sys/devices/.*/usb\d+/\d+-[\d.]+)/", path)
    assert usb, path
    return router.sysfs(f"{usb.group(1)}/speed")


def test_usb_host_controllers_are_bound(router):
    drivers = router.run("ls /sys/bus/platform/drivers")
    for name in ("xhci-hcd", "ehci-platform", "ohci-platform"):
        assert name in drivers.split(), name
        assert router.run(f"ls /sys/bus/platform/drivers/{name} | grep -c usb; true").strip() != "0"


def test_usb_disk_uses_uas_at_superspeed(router):
    disks = usb_disks(router)
    if not disks:
        pytest.skip("no USB disk is plugged in")
    for name, path in disks.items():
        if port_speed(router, path) == "5000":
            interface = re.search(r"(/sys/devices/.*/\d+-[\d.]+:\d+\.\d+)/", path)
            assert interface, path
            driver = router.run(f"readlink -f {interface.group(1)}/driver").strip()
            assert driver.endswith("/uas"), f"{name} is driven by {driver}"
            return
    pytest.skip("no disk sits in the USB 3.0 port")


def test_usb_disk_mounts_read_only(router):
    disks = usb_disks(router)
    if not disks:
        pytest.skip("no USB disk is plugged in")
    name = sorted(disks)[0]
    partition = router.run(f"ls /sys/block/{name} | grep -m1 '^{name}[0-9]' || echo {name}").strip()
    mount = "/tmp/hardware-test-mount"
    try:
        router.run(f"mkdir -p {mount} && mount -o ro /dev/{partition} {mount}")
        assert f" {mount} " in router.run("cat /proc/mounts")
        router.run(f"ls {mount} > /dev/null")
    finally:
        router.run(f"umount {mount} 2>/dev/null; rmdir {mount}; true")


@pytest.mark.guided
@pytest.mark.parametrize("port,speed", [("USB 3.0 (blue)", "5000"), ("USB 2.0 (black)", "480")])
def test_each_usb_port_enumerates(router, port, speed):
    say(f"Plug a USB drive into the {port} port, the only USB device connected.")
    disks = {}
    for _ in range(20):
        disks = usb_disks(router)
        if disks:
            break
        router.run("sleep 1")
    assert disks, "no USB disk appeared"
    assert {port_speed(router, path) for path in disks.values()} == {speed}
