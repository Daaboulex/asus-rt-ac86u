import json
import re

import pytest
from conftest import RADIO_2G_SLOT, RADIO_5G_SLOT, phys, radio_section

NVRAM = "/lib/firmware/brcm/brcmfmac4366c-pcie.asus,rt-ac86u.txt"
BOARD_FIRMWARE_PACKAGE = "brcmfmac-firmware-4366c0-pcie-rt-ac86u"
GET_VAR_HEADER = [0x06, 0x01, 0, 0, 0x40, 0, 0, 0, 0x14, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]


def firmware_variable(router, interface: str, name: str, argument: bytes = b"") -> list[int]:
    request = GET_VAR_HEADER + list(name.encode()) + [0] + list(argument)
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


def test_radios_run_the_board_firmware_package(router):
    listing = router.run(f"apk list -I {BOARD_FIRMWARE_PACKAGE} 2>/dev/null; true")
    shipped = re.search(rf"{BOARD_FIRMWARE_PACKAGE}-(\d+(?:\.\d+)+)-r\d+", listing)
    assert shipped, f"{BOARD_FIRMWARE_PACKAGE} is not installed: {listing!r}"
    loaded = re.findall(r"Firmware: BCM4366[46]/\d+ wl0: .* version (\S+) \(r\d+\)", router.dmesg())
    assert loaded == [shipped.group(1)] * 2, f"loaded {loaded}, shipped {shipped.group(1)}"


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
    rated = []
    for ap in access_points(router):
        interface = ap.removeprefix("hostapd.")
        dump = router.run(f"iw dev {interface} station dump")
        for block in re.split(r"(?m)^(?=Station )", dump):
            if not block.startswith("Station "):
                continue
            for field in ("signal:", "tx bitrate:", "rx bitrate:", "rx bytes:", "tx packets:"):
                assert field in block, f"{interface}: no {field!r} in\n{block}"
            checked.append(interface)
            rated.extend(re.findall(r"(?m)^\s*[tr]x bitrate:.*\bMCS\b.*$", block))
    if not checked:
        pytest.skip("no station is associated")
    assert rated, "no station reports an HT or VHT rate with its MCS"


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


def radio_access_points(router) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    running = access_points(router)
    for phy in router.run("ls /sys/class/ieee80211").split():
        interfaces = router.run(
            f"ls /sys/class/ieee80211/{phy}/device/net 2>/dev/null; true"
        ).split()
        aps = [i for i in interfaces if f"hostapd.{i}" in running]
        if aps:
            found[phy] = sorted(aps)
    return found


def firmware_bsscfgs(router, interface: str) -> list[int]:
    held = []
    for index in range(16):
        try:
            firmware_variable(router, interface, "bsscfg:bss", index.to_bytes(4, "little"))
        except AssertionError:
            continue
        held.append(index)
    return held


def assert_one_bsscfg_per_access_point(router):
    radios = radio_access_points(router)
    if not radios:
        pytest.skip("no access point is configured")
    for phy, aps in radios.items():
        held = firmware_bsscfgs(router, aps[0])
        assert len(held) == len(aps), f"{phy}: bsscfgs {held} for access points {aps}"


def test_firmware_holds_one_bsscfg_per_access_point(router):
    assert_one_bsscfg_per_access_point(router)


@pytest.mark.disruptive
def test_wifi_restart_keeps_one_bsscfg_per_access_point(router):
    router.run("wifi down; sleep 5; wifi up; sleep 60", timeout=150)
    assert_one_bsscfg_per_access_point(router)


def test_sae_access_points_beacon_the_hash_to_element_they_offer(router):
    offered = []
    for aps in radio_access_points(router).values():
        for interface in aps:
            bss = hostapd_bss(router, interface)
            if "SAE" in bss.get("wpa_key_mgmt", "").split() and bss.get("sae_pwe") in ("1", "2"):
                offered.append(interface)
    if not offered:
        pytest.skip("no access point offers SAE hash-to-element")
    refused = [line for line in router.dmesg().splitlines() if "firmware takes no RSNXE" in line]
    assert not refused, f"{offered} offer hash-to-element, but:\n" + "\n".join(refused)


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
