# Changelog

All notable changes to this project are recorded here, following
[Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

Current version: 0.1.0, not yet tagged. An OpenWrt port for the ASUS RT-AC86U,
also sold as the RT-AC2900, and `asus-rescue`, the Linux tool that flashes it.

### Added

- `asus-rescue probe` finds a router in rescue mode without writing to it.
- `asus-rescue flash` uploads an image through rescue mode. It refuses an
  image whose SHA256 differs from the one stated, before it sends a packet,
  and reports success only when the router does. `--dry-run` shows the plan.
- A patch series that adds the RT-AC86U to OpenWrt main, and `openwrt-build`,
  which builds the image from the OpenWrt, `packages` and `luci` commits
  pinned in `flake.lock`.
- A check that the series applies to the pinned OpenWrt tree and that its
  kernel patches sit under the kernel version the board's target builds.
- `hardware-test`, which checks a running router over SSH.
- A Firmware workflow that builds the image on a GitHub runner, keeps it with
  its checksums as an artifact, and opens an issue when the build fails.
- The image carries WireGuard, the cake shaper with `sqm-scripts`, `pbr`,
  `iperf3` and the USB-serial drivers `cp210x`, `ch341` and `cdc-acm`, since
  no kernel module can be installed from OpenWrt's feed afterwards.
- `iw-full` replaces `iw`, so the radio firmware's power targets can be
  read, and a hardware test checks that a configured transmit power caps
  every chain.
- A device whose MAC address is in the firewall IP set `isolated` gets an
  address and answers what other devices start, and reaches nothing: no
  internet, no DNS, no router, no other device. A hardware test checks it
  with two clients on the bridge.
- `port-update` updates a router from this repository's releases, off until
  switched on: to the newest release a few days old, signed with the release
  key the image trusts, in a quiet night window. It keeps the image it ran,
  notes what works before the update, with any checks the owner adds as files
  on the router, and flashes the old image back when the update loses any of
  it. The Firmware workflow signs every build of `main` and publishes it as
  a release. Each image names its commit in `/etc/port_release`.
- The README installs from a signed release as well as from a build of your
  own, says which key a router trusts, and how a fork publishes its own
  releases.

### Changed

- The series no longer raises the `PKG_RELEASE` of OpenWrt's packages, so an
  upstream bump no longer breaks the patches after it. The image follows
  OpenWrt main past the removal of `brcmsmac`.

### Fixed

- `openwrt-build` copies every file of the pinned trees that changed, also
  one whose size stayed the same. Every file in the Nix store carries the
  same time, so a rebuild after the pins moved kept such a file stale and
  could mix the old and the new tree.
