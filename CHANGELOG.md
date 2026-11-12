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
