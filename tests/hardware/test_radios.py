import json
import re

import pytest
from conftest import RADIO_2G_SLOT, RADIO_5G_SLOT, phys, radio_section

NVRAM = "/lib/firmware/brcm/brcmfmac4366c-pcie.asus,rt-ac86u.txt"
GET_VAR_HEADER = [0x06, 0x01, 0, 0, 0x40, 0, 0, 0, 0x14, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]


def firmware_variable(router, interface: str, name: str) -> list[int]:
    request = GET_VAR_HEADER + list(name.encode()) + [0]
    output = router.run(
        f"iw dev {interface} vendor recv 0x001018 0x1 " + " ".join(f"0x{b:02x}" for b in request)
    )
    return [
        int(byte, 16)
        for line in output.splitlines()
        for byte in line.removeprefix("vendor response:").split()
    ]


def mac_plus(base: str, offset: int) -> str:
    value = int(base.replace(":", ""), 16) + offset
    raw = f"{value:012x}"
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def test_both_radios_start_their_firmware(router):
    log = router.dmesg()
    assert len(re.findall(r"brcmf_c_preinit_dcmds: Firmware: BCM4366[46]", log)) == 2
    assert set(phys(router)) == {RADIO_2G_SLOT, RADIO_5G_SLOT}


def test_radio_calibration_comes_from_the_unit(router):
    nvram = router.run(f"cat {NVRAM}")
    assert "devpath0=pcie/1/1/" in nvram
    assert "devpath1=pcie/2/1/" in nvram
    assert re.search(r"^0:leddc=0x[0-9a-f]+$", nvram, re.M)
    assert re.search(r"^1:leddc=0x[0-9a-f]+$", nvram, re.M)
    assert len(re.findall(r"^[01]:", nvram, re.M)) > 100


def test_radio_macs_follow_the_vendor_layout(router):
    base = router.sysfs("/sys/class/net/lan1/address")
    found = phys(router)
    assert router.sysfs(f"/sys/class/ieee80211/{found[RADIO_2G_SLOT]}/macaddress") == base
    assert router.sysfs(f"/sys/class/ieee80211/{found[RADIO_5G_SLOT]}/macaddress") == mac_plus(
        base, 4
    )


def test_each_radio_serves_one_band(router):
    found = phys(router)
    info_2g = router.run(f"iw phy {found[RADIO_2G_SLOT]} info")
    info_5g = router.run(f"iw phy {found[RADIO_5G_SLOT]} info")
    assert "Band 1:" in info_2g and "Band 2:" not in info_2g
    assert "Band 2:" in info_5g and "Band 1:" not in info_5g


def access_points(router) -> list[str]:
    return [line for line in router.run("ubus list 'hostapd.*'").split() if line]


def test_access_points_are_enabled(router):
    aps = access_points(router)
    if not aps:
        pytest.skip("no access point is configured")
    for ap in aps:
        status = json.loads(router.run(f"ubus call {ap} get_status"))
        assert status["status"] == "ENABLED", f"{ap}: {status['status']}"


def test_channel_survey_reports_busy_time(router):
    aps = access_points(router)
    if not aps:
        pytest.skip("no access point is configured")
    for ap in aps:
        interface = ap.removeprefix("hostapd.")
        router.run(f"iw dev {interface} scan ap-force > /dev/null")
        assert "channel busy time" in router.run(f"iw dev {interface} survey dump"), interface


def test_channel_survey_reports_each_channels_own_noise(router):
    phy = phys(router)[RADIO_2G_SLOT]
    aps = [
        ap.removeprefix("hostapd.")
        for ap in access_points(router)
        if ap.startswith(f"hostapd.{phy}-")
    ]
    if not aps:
        pytest.skip("no 2.4 GHz access point is configured")
    router.run(f"iw dev {aps[0]} scan ap-force > /dev/null")
    noise = [
        int(n)
        for n in re.findall(r"noise:\s+(-\d+) dBm", router.run(f"iw dev {aps[0]} survey dump"))
    ]
    assert len(noise) >= 3, noise
    assert len(set(noise)) > 1, noise


def test_station_dump_carries_signal_rates_and_counters(router):
    checked = []
    for ap in access_points(router):
        interface = ap.removeprefix("hostapd.")
        dump = router.run(f"iw dev {interface} station dump")
        for block in re.split(r"(?m)^(?=Station )", dump):
            if not block.startswith("Station "):
                continue
            for field in ("signal:", "tx bitrate:", "rx bitrate:", "rx bytes:", "tx packets:"):
                assert field in block, f"{interface}: no {field!r} in\n{block}"
            checked.append(interface)
    if not checked:
        pytest.skip("no station is associated")


def hostapd_bss(router, interface: str) -> dict[str, str]:
    phy = interface.split("-")[0]
    fields: dict[str, str] = {}
    inside = False
    for line in router.run(f"cat /var/run/hostapd-{phy}.conf").splitlines():
        key, _, value = line.partition("=")
        if key in ("interface", "bss"):
            inside = value == interface
        elif inside:
            fields[key] = value
    return fields


def test_firmware_beacons_the_rsnxe_hostapd_builds(router):
    checked = []
    for ap in access_points(router):
        interface = ap.removeprefix("hostapd.")
        if not interface.endswith("-ap0"):
            continue
        try:
            held = firmware_variable(router, interface, "rsnxe")
        except AssertionError:
            continue
        bss = hostapd_bss(router, interface)
        h2e = "SAE" in bss.get("wpa_key_mgmt", "").split() and bss.get("sae_pwe", "2") in ("1", "2")
        element = held[4 : 6 + held[5]] if len(held) > 5 and held[4] == 0xF4 else []
        if h2e:
            assert element and element[2] & 0x20, f"{interface}: firmware holds {element}"
        else:
            assert not element or not element[2] & 0x20, f"{interface}: firmware holds {element}"
        checked.append(interface)
    if not checked:
        pytest.skip("no running firmware has the rsnxe iovar")


def test_radios_take_msi_interrupts(router):
    lines = [
        line
        for line in router.run("cat /proc/interrupts").splitlines()
        if "brcmf_pcie_intr" in line
    ]
    assert len(lines) == 2, lines
    for line in lines:
        assert "MSI" in line, line


def test_configured_transmit_power_caps_every_chain(router):
    found = phys(router)
    checked = []
    for slot in (RADIO_2G_SLOT, RADIO_5G_SLOT):
        section = radio_section(router, slot)
        if router.run(f"uci -q get wireless.{section}.disabled; true").strip() == "1":
            continue
        cap = router.run(f"uci -q get wireless.{section}.txpower; true").strip()
        interfaces = router.run(
            f"ls /sys/class/ieee80211/{found[slot]}/device/net 2>/dev/null; true"
        ).split()
        if not cap or not interfaces:
            continue
        target = firmware_variable(router, interfaces[0], "txpwr_target_max")
        chains = target[10 : 10 + target[14]]
        assert chains, f"{interfaces[0]}: no chain in {target}"
        dbm = [chain / 4 for chain in chains]
        assert max(dbm) <= int(cap), f"{interfaces[0]}: {dbm} dBm, cap {cap}"
        checked.append(slot)
    if not checked:
        pytest.skip("no running radio has a transmit power set")


@pytest.mark.disruptive
@pytest.mark.xfail(reason="on a radar channel the scan stalls; brcmfmac has no CAC", strict=True)
def test_access_point_starts_on_a_radar_channel(router):
    radio = radio_section(router, RADIO_5G_SLOT)
    channel = router.run(f"uci get wireless.{radio}.channel").strip()
    ap = f"hostapd.{phys(router)[RADIO_5G_SLOT]}-ap0"
    try:
        router.run(f"uci set wireless.{radio}.channel=52 && uci commit wireless && wifi up {radio}")
        router.run("sleep 90")
        status = json.loads(router.run(f"ubus call {ap} get_status"))
        assert status["status"] == "ENABLED"
    finally:
        router.run(f"uci set wireless.{radio}.channel={channel} && uci commit wireless")
        router.run(f"wifi up {radio}")
