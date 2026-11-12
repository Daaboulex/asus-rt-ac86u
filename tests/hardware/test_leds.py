import time

import pytest
from conftest import LEDS, RADIO_2G_SLOT, RADIO_5G_SLOT, ask, phys, radio_section


def test_every_led_is_registered(router):
    present = set(router.run("ls /sys/class/leds").split())
    missing = [name for name in LEDS if name not in present]
    assert not missing, missing


def wan_is_up(router) -> bool:
    return "true" in router.run("ifstatus wan | jsonfilter -e '@.up'")


@pytest.mark.disruptive
def test_internet_led_shows_the_wan_state(router):
    if not wan_is_up(router):
        pytest.skip("wan is not up, so the up state cannot be checked")
    try:
        router.run("ifdown wan")
        time.sleep(4)
        assert router.led("red:wan")[0] > 0
        assert router.led("white:wan")[0] == 0
    finally:
        router.run("ifup wan")
    for _ in range(20):
        time.sleep(2)
        if wan_is_up(router):
            break
    time.sleep(2)
    assert router.led("red:wan")[0] == 0
    assert router.led("white:wan")[1] == "netdev"


@pytest.mark.disruptive
@pytest.mark.parametrize("slot", [RADIO_2G_SLOT, RADIO_5G_SLOT])
def test_wifi_led_follows_its_access_point(router, slot):
    led = f"brcmfmac-{phys(router)[slot]}"
    section = radio_section(router, slot)
    if router.run(f"uci -q get wireless.{section}.disabled; true").strip() == "1":
        pytest.skip(f"{section} is disabled in the configuration")
    try:
        router.run(f"uci set wireless.{section}.disabled=1 && uci commit wireless && wifi")
        time.sleep(10)
        assert router.led(led)[0] == 0
    finally:
        router.run(f"uci set wireless.{section}.disabled=0 && uci commit wireless && wifi")
    time.sleep(12)
    assert router.led(led) == (1, "netdev")


@pytest.mark.guided
@pytest.mark.parametrize(
    "led,question",
    [
        ("white:power", "Is the power LED lit, steady?"),
        ("white:wan", "Is the internet LED white (WAN has an address)?"),
        ("brcmfmac-phy0", "Is the 2.4 GHz LED lit?"),
        ("brcmfmac-phy1", "Is the 5 GHz LED lit?"),
    ],
)
def test_led_is_seen_lit(router, led, question):
    assert router.led(led)[0] > 0, f"{led} is off in sysfs, nothing to look at"
    assert ask(question)


@pytest.mark.guided
def test_wifi_led_blinks_through_the_firmware(router):
    led = "/sys/class/leds/brcmfmac-phy1"
    trigger = router.led("brcmfmac-phy1")[1]
    try:
        router.run(f"echo timer > {led}/trigger")
        router.run(f"echo 200 > {led}/delay_on; echo 200 > {led}/delay_off")
        assert ask("Is the 5 GHz LED blinking about twice a second?")
    finally:
        router.run(f"echo {trigger} > {led}/trigger; /etc/init.d/led restart")
