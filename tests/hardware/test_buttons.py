import re
import time

import pytest
from conftest import say

BUTTONS = {
    "Reset": "reset",
    "WPS": "wps",
    "WiFi": "rfkill",
    "LEDs": "brightness_zero",
}


def level(router, label: str) -> str:
    table = router.run("cat /sys/kernel/debug/gpio")
    match = re.search(rf"\|{label}\s*\)\s+in\s+(hi|lo)", table)
    assert match, f"no GPIO labelled {label}"
    return match.group(1)


def wait_for(router, label: str, wanted: str, limit: int) -> bool:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if level(router, label) == wanted:
            return True
        time.sleep(0.3)
    return False


def test_buttons_read_released(router):
    for label in BUTTONS:
        assert level(router, label) == "hi", f"{label} reads pressed with nobody touching it"


@pytest.mark.guided
@pytest.mark.parametrize("label", list(BUTTONS))
def test_button_press_reaches_the_kernel(router, label):
    handler = f"/etc/rc.button/{BUTTONS[label]}"
    original = router.run(f"cat {handler}")
    router.run("printf '#!/bin/sh\\nexit 0\\n' > /tmp/noop-button && chmod +x /tmp/noop-button")
    router.run(f"mount --bind /tmp/noop-button {handler}")
    try:
        say(f"Press and hold the {label} button for about two seconds, then let go.")
        assert wait_for(router, label, "lo", 30), f"{label} never read pressed"
        assert wait_for(router, label, "hi", 30), f"{label} never read released"
    finally:
        router.run(f"umount {handler}")
    assert router.run(f"cat {handler}") == original
