import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REMOTE = "/tmp/hardware-test-port-update"
IMAGE = "openwrt-bcm4908-generic-asus_rt-ac86u-squashfs.bin"
SITE = "/tmp/hardware-test-site"
SOURCE = "http://127.0.0.1:8471"
STATE = "/etc/port-update"
TEST_KEYS = f"{STATE}/hardware-test-keys"
TEST_CHECK = f"{STATE}/checks/hardware-test"
OLD = "2000-01-01T00:00:00Z"
UPDATER = f"UCI_CONFIG_DIR={REMOTE}/config /usr/sbin/port-update"


def signify(*args: str, cwd) -> None:
    subprocess.run(["signify", *args], cwd=cwd, check=True, capture_output=True)


def signed(directory: Path, image: bytes, key: Path) -> None:
    directory.mkdir(parents=True)
    (directory / IMAGE).write_bytes(image)
    digest = hashlib.sha256(image).hexdigest()
    (directory / "SHA256SUMS").write_text(f"{digest}  {IMAGE}\n")
    signify("-S", "-s", str(key), "-m", "SHA256SUMS", "-x", "SHA256SUMS.sig", cwd=directory)


def configure(router, options: dict[str, str]) -> None:
    lines = "".join(f"\\toption {name} '{value}'\\n" for name, value in options.items())
    router.run(
        f"mkdir -p {REMOTE}/config && "
        f"printf 'config port_update main\\n{lines}' > {REMOTE}/config/port_update"
    )


def release_json(tag: str, published: str = OLD, prerelease: bool = False) -> dict:
    names = (IMAGE, "SHA256SUMS", "SHA256SUMS.sig")
    return {
        "tag_name": tag,
        "published_at": published,
        "prerelease": prerelease,
        "assets": [{"name": n, "browser_download_url": f"{SOURCE}/image/{n}"} for n in names],
    }


def publish(root: Path, releases: list[dict]) -> None:
    listing = root / "releases" / "index.html"
    listing.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text(json.dumps(releases))


def serve(router, root: Path) -> None:
    archive = root.parent / "site.tar"
    subprocess.run(["tar", "-C", str(root), "-cf", str(archive), "."], check=True)
    router.run(f"rm -rf {SITE} && mkdir -p {SITE}")
    router.upload(archive, f"{SITE}.tar")
    router.run(
        f"tar -C {SITE} -xf {SITE}.tar && rm {SITE}.tar && "
        f"(uhttpd -f -p {SOURCE.removeprefix('http://')} -h {SITE} >/dev/null 2>&1 & "
        f"echo $! > {SITE}.pid)"
    )
    probe = f"uclient-fetch -q -O /dev/null {SOURCE}/releases"
    deadline = time.monotonic() + 30
    while router.ssh(probe).returncode != 0:
        assert time.monotonic() < deadline, "the router does not serve the test releases"
        time.sleep(1)


def stop_serving(router) -> None:
    router.run(f"[ -f {SITE}.pid ] && kill $(cat {SITE}.pid); rm -rf {SITE} {SITE}.pid {SITE}.tar")


def running_tag(router) -> str:
    return f"build-{router.run('cat /etc/port_release').strip()[:12]}"


@pytest.fixture
def remote(router):
    router.run(f"rm -rf {REMOTE} && mkdir -p {REMOTE}")
    yield
    router.ssh(f"rm -rf {REMOTE} /tmp/port-update")


def test_the_image_names_the_commit_it_was_built_from(router):
    stamp = router.run("cat /etc/port_release").strip()
    assert re.fullmatch(r"[0-9a-f]{40}(-dirty)?", stamp), f"/etc/port_release holds {stamp!r}"


def test_the_image_trusts_the_release_key_under_its_usign_id(router):
    listing = router.run(f'for k in {STATE}/keys/*; do echo "${{k##*/}} $(usign -F -p "$k")"; done')
    pairs = [line.split() for line in listing.splitlines()]
    assert pairs, "the image ships no trusted key"
    assert all(name == fingerprint for name, fingerprint in pairs), (
        f"a key file is not named by its usign id: {pairs}"
    )
    shipped = router.run(f"cat {STATE}/keys/{pairs[0][0]}")
    assert shipped == (REPO / "openwrt" / "release-key.pub").read_text(), (
        "the image trusts another key than openwrt/release-key.pub"
    )


def test_an_update_needs_a_trusted_signature_and_its_checksum(router, remote, tmp_path):
    for name in ("trusted", "foreign"):
        signify("-G", "-n", "-p", f"{name}.pub", "-s", f"{name}.sec", cwd=tmp_path)
    image = b"image bytes the router never flashes\n"
    signed(tmp_path / "good", image, tmp_path / "trusted.sec")
    signed(tmp_path / "foreign-signed", image, tmp_path / "foreign.sec")
    signed(tmp_path / "tampered", image, tmp_path / "trusted.sec")
    with (tmp_path / "tampered" / IMAGE).open("ab") as tampered:
        tampered.write(b"changed after signing\n")
    archive = tmp_path / "releases.tar"
    subprocess.run(
        ["tar", "-cf", str(archive), "trusted.pub", "good", "foreign-signed", "tampered"],
        cwd=tmp_path,
        check=True,
    )
    router.upload(archive, f"{REMOTE}/releases.tar")
    router.run(f"tar -C {REMOTE} -xf {REMOTE}/releases.tar")
    configure(router, {"keys": f"{REMOTE}/keys"})
    router.run(f"{UPDATER} trust {REMOTE}/trusted.pub")
    assert router.ssh(f"{UPDATER} verify {REMOTE}/good {IMAGE}").returncode == 0, (
        "a release signed by a trusted key was refused"
    )
    foreign = router.ssh(f"{UPDATER} verify {REMOTE}/foreign-signed {IMAGE}")
    assert foreign.returncode != 0, "a release signed by an untrusted key was accepted"
    tampered = router.ssh(f"{UPDATER} verify {REMOTE}/tampered {IMAGE}")
    assert tampered.returncode != 0, "an image changed after signing was accepted"


def test_the_router_picks_the_newest_release_old_enough_and_newer_than_its_own(
    router, remote, tmp_path
):
    running = release_json(running_tag(router))
    today = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    young = release_json("build-test-young", published=today)
    newer = release_json("build-test-newer")
    older = release_json("build-test-older")
    prerelease = release_json("build-test-prerelease", prerelease=True)
    cases = [
        ([running], "next: none"),
        ([newer, running], "next: build-test-newer"),
        ([young, running], "next: none"),
        ([young, newer, running], "next: build-test-newer"),
        ([prerelease, running], "next: none"),
        ([running, older], "next: none"),
    ]
    configure(router, {"url": f"{SOURCE}/releases", "min_age_days": "3"})
    root = tmp_path / "site"
    publish(root, [running])
    serve(router, root)
    try:
        for releases, expected in cases:
            publish(root, releases)
            router.upload(root / "releases" / "index.html", f"{SITE}/releases/index.html")
            answer = router.run(f"{UPDATER} check")
            picked = next(line for line in answer.splitlines() if line.startswith("next:"))
            order = [r["tag_name"] for r in releases]
            assert picked.startswith(expected), f"for {order} the router chose {picked!r}"
    finally:
        stop_serving(router)


def test_the_check_watches_what_works_now(router):
    answer = router.run("/usr/sbin/port-update check")
    watched = next(line for line in answer.splitlines() if line.startswith("watched:"))
    for item in ("interface lan", "interface wan", "service dnsmasq", "dns", "no crash"):
        assert item in watched, f"the update check does not watch {item!r}: {watched}"
    services = re.findall(r"service ([^;]+);", watched)
    for name in services:
        respawned = router.ssh(
            f'ubus call service list \'{{"name":"{name}"}}\' | '
            "jsonfilter -e '@.*.instances[@.running=true].respawn'"
        )
        assert respawned.returncode == 0, (
            f"the update check watches {name}, which procd does not keep alive, so a run "
            "that ends by itself would read as lost"
        )


def test_the_owners_checks_join_the_watch_and_report_what_fails(router, remote):
    scripts = {
        "passes": "exit 0",
        "fails": "exit 1",
        "hangs": "sleep 30",
    }
    for name, body in scripts.items():
        router.run(
            f"mkdir -p {REMOTE}/checks && printf '#!/bin/sh\\n{body}\\n' > {REMOTE}/checks/{name} "
            f"&& chmod +x {REMOTE}/checks/{name}"
        )
    router.run(f"printf '#!/bin/sh\\nexit 1\\n' > {REMOTE}/checks/switched-off")
    configure(router, {"checks": f"{REMOTE}/checks", "check_timeout": "2"})
    answer = router.run(f"{UPDATER} check", timeout=60)
    watched = next(line for line in answer.splitlines() if line.startswith("watched:"))
    failing = next(line for line in answer.splitlines() if line.startswith("failing now:"))
    assert "check passes;" in watched, f"a passing check is not watched: {watched}"
    for name in ("fails", "hangs", "switched-off"):
        assert f"check {name};" not in watched, f"the failing check {name} is watched"
    assert "fails;" in failing and "hangs;" in failing, f"failing checks not reported: {failing}"
    assert "switched-off" not in failing, "a check that is not executable still runs"


def settled(router) -> None:
    deadline = time.monotonic() + 600
    while router.ssh(f"[ ! -f {STATE}/pending ]").returncode != 0:
        assert time.monotonic() < deadline, "the updated image never finished its checks"
        time.sleep(5)


def update(router, root: Path, releases: list[dict]) -> str:
    publish(root, releases)
    serve(router, root)
    old = router.boot_id()
    router.ssh("(/usr/sbin/port-update run > /dev/null 2>&1 &)")
    return router.wait_for_new_boot(old, limit=600)


@pytest.mark.destructive
def test_an_update_flashes_a_signed_release_and_goes_back_when_it_loses_a_check(router, tmp_path):
    image = Path(os.environ.get("ROUTER_IMAGE", ""))
    if not image.is_file():
        pytest.skip("set ROUTER_IMAGE to the image the router runs")
    if router.ssh(f"[ ! -e {STATE}/previous.bin ] && [ ! -e {STATE}/pending ]").returncode:
        pytest.skip("the router keeps updater state of its own, which this test would replace")
    running = running_tag(router)
    signify("-G", "-n", "-p", "test.pub", "-s", "test.sec", cwd=tmp_path)
    root = tmp_path / "site"
    signed(root / "image", image.read_bytes(), tmp_path / "test.sec")
    (root / "releases" / "tags").mkdir(parents=True)
    (root / "releases" / "tags" / running).write_text(json.dumps(release_json(running)))
    saved = router.run("cat /etc/config/port_update")
    try:
        router.upload(tmp_path / "test.pub", "/tmp/hardware-test-release.pub")
        router.run(
            "uci batch <<EOF\n"
            "set port_update.main.enabled=1\n"
            f"set port_update.main.url={SOURCE}/releases\n"
            f"set port_update.main.keys={TEST_KEYS}\n"
            "set port_update.main.min_age_days=0\n"
            "set port_update.main.start=0000\n"
            "set port_update.main.end=2400\n"
            "set port_update.main.idle_pps=1000000000\n"
            "set port_update.main.idle_window=1\n"
            "set port_update.main.settle=240\n"
            "commit port_update\n"
            "EOF\n"
            "/usr/sbin/port-update trust /tmp/hardware-test-release.pub"
        )
        good = release_json("build-test-good")
        update(router, root, [good, release_json(running)])
        settled(router)
        healthy = router.ssh(f"grep -qx build-test-good {STATE}/bad")
        assert healthy.returncode != 0, "a healthy update failed its checks"
        assert router.ssh(f"[ -f {STATE}/previous.bin ]").returncode == 0, (
            "a healthy update kept no image to go back to"
        )
        router.run(
            f"mkdir -p {STATE}/checks && touch /tmp/hardware-test-marker && "
            f"printf '#!/bin/sh\\n[ -e /tmp/hardware-test-marker ]\\n' > {TEST_CHECK} && "
            f"chmod +x {TEST_CHECK}"
        )
        updated = update(router, root, [release_json("build-test-bad"), good])
        router.wait_for_new_boot(updated, limit=600)
        assert "build-test-bad" in router.run(f"cat {STATE}/bad").split(), (
            "an update that failed its checks was not marked bad"
        )
        gone = router.ssh(f"[ ! -e {STATE}/pending ] && [ ! -e {STATE}/pending.bin ]")
        assert gone.returncode == 0, "the failed update left its pending image behind"
    finally:
        archive = tmp_path / "port_update"
        archive.write_text(saved)
        router.upload(archive, "/etc/config/port_update")
        stop_serving(router)
        router.run(
            f"rm -rf {TEST_KEYS} {TEST_CHECK} /tmp/hardware-test-release.pub "
            f"/tmp/hardware-test-marker {STATE}/previous.bin {STATE}/pending "
            f"{STATE}/pending.bin {STATE}/bad {STATE}/before"
        )
