import time

import pytest
from conftest import SWITCH_PORTS, say


def carrier(router, port: str) -> bool:
    return router.sysfs(f"/sys/class/net/{port}/carrier") == "1"


def test_switch_ports_exist_behind_the_cpu_port(router):
    for port in SWITCH_PORTS:
        assert (
            router.run(f"readlink -f /sys/class/net/{port}/device/driver")
            .strip()
            .endswith("brcm-sf2")
        ), port


def test_wan_has_its_own_mac(router):
    assert router.sysfs("/sys/class/net/wan/address") != router.sysfs("/sys/class/net/lan1/address")


def test_wan_gets_an_address_when_connected(router):
    if not carrier(router, "wan"):
        pytest.skip("no cable in the WAN port")
    address = router.run("ifstatus wan | jsonfilter -e '@[\"ipv4-address\"][0].address'").strip()
    assert address, "wan has a link but no IPv4 address"


def test_linked_ports_run_at_gigabit(router):
    linked = [port for port in SWITCH_PORTS if carrier(router, port)]
    assert linked, "no port has a link"
    for port in linked:
        assert router.sysfs(f"/sys/class/net/{port}/speed") == "1000", port


@pytest.mark.guided
@pytest.mark.parametrize("port", ["lan2", "lan3", "lan4", "lan1"])
def test_each_lan_port_links(router, port):
    say(f"Move the LAN cable into {port.upper()} and wait for its LED.")
    for _ in range(20):
        if carrier(router, port):
            break
        time.sleep(1)
    assert carrier(router, port), f"{port} has no link"
    assert router.sysfs(f"/sys/class/net/{port}/speed") == "1000"
