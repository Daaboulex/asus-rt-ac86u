import pytest


def test_wireguard_interface_can_be_created(router):
    try:
        router.run("ip link add hwtest-wg type wireguard")
        assert "interface: hwtest-wg" in router.run("wg show hwtest-wg")
    finally:
        router.run("ip link del hwtest-wg 2>/dev/null; true")


def test_cake_shapes_an_interface(router):
    try:
        router.run("ip link add hwtest-ifb type ifb")
        router.run("tc qdisc replace dev hwtest-ifb root cake bandwidth 100mbit")
        assert "qdisc cake" in router.run("tc qdisc show dev hwtest-ifb")
    finally:
        router.run("ip link del hwtest-ifb 2>/dev/null; true")


@pytest.mark.parametrize("module", ["cp210x", "ch341", "cdc_acm"])
def test_usb_serial_driver_is_loaded(router, module):
    assert router.run(f"test -d /sys/module/{module} && echo loaded; true").strip() == "loaded"


def test_dns_services_ship_switched_off(router):
    assert router.run("uci -c /rom/etc/config get adblock.global.adb_enabled").strip() == "0"
    shipped = router.run("uci -c /rom/etc/config show https-dns-proxy")
    resolvers = [line for line in shipped.splitlines() if line.endswith("=https-dns-proxy")]
    assert not resolvers, shipped
    for option in ("force_dns", "canary_domains_icloud", "canary_domains_mozilla"):
        assert f"https-dns-proxy.config.{option}='0'" in shipped, shipped


@pytest.mark.parametrize("package", ["pbr", "sqm"])
def test_added_service_ships_switched_off(router, package):
    shipped = router.run(f"uci -c /rom/etc/config show {package}")
    switches = [line.split("=", 1)[1] for line in shipped.splitlines() if ".enabled=" in line]
    assert switches, f"/rom/etc/config/{package} has no enabled option"
    assert set(switches) == {"'0'"}, shipped
