import json
import re

import pytest
from conftest import RADIO_2G_SLOT, RADIO_5G_SLOT, phys, radio_section

NVRAM = "/lib/firmware/brcm/brcmfmac4366c-pcie.asus,rt-ac86u.txt"


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


@pytest.mark.disruptive
@pytest.mark.xfail(reason="brcmfmac reports no CAC events, so hostapd waits on DFS", strict=True)
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
