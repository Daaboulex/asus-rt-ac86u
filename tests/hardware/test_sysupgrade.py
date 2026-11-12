import hashlib
import os
import uuid
from pathlib import Path

import pytest


def test_sysupgrade_refuses_a_broken_image(router, tmp_path):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(os.urandom(512 * 1024))
    router.upload(junk, "/tmp/hardware-test-junk.bin")
    try:
        assert router.ssh("sysupgrade -T /tmp/hardware-test-junk.bin").returncode != 0
    finally:
        router.run("rm -f /tmp/hardware-test-junk.bin")


@pytest.mark.destructive
def test_sysupgrade_keeps_settings(router):
    image = Path(os.environ.get("ROUTER_IMAGE", ""))
    if not image.is_file():
        pytest.skip("set ROUTER_IMAGE to the image to flash")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    marker = uuid.uuid4().hex
    router.run(
        "uci set system.hardwaretest=marker && "
        f"uci set system.hardwaretest.value={marker} && uci commit system"
    )
    router.upload(image, "/tmp/hardware-test.bin")
    assert router.run("sha256sum /tmp/hardware-test.bin").split()[0] == digest
    assert router.ssh("sysupgrade -T /tmp/hardware-test.bin").returncode == 0
    old = router.boot_id()
    router.ssh("(sysupgrade /tmp/hardware-test.bin > /dev/null 2>&1 &)")
    router.wait_for_new_boot(old, limit=420)
    try:
        assert router.run("uci -q get system.hardwaretest.value").strip() == marker
    finally:
        router.run("uci -q delete system.hardwaretest; uci commit system")
