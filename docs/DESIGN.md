# DESIGN: the RT-AC86U port

The RT-AC86U is out of vendor and Asuswrt-Merlin support, and upstream
OpenWrt carries its SoC family but not this board. This file says how the
port is built so it stays correct, small and upstreamable: the shape
of the work, what it guarantees and the open decisions. Facts carry their
source. What does not work is in [`COMPATIBILITY.md`](./COMPATIBILITY.md);
building, checks and updates are in [`DEVELOPMENT.md`](./DEVELOPMENT.md).

## Principles

- Every change is a patch to the pinned OpenWrt tree, in the place and form
  upstream expects. The series stays in this repository until the port is
  finished (owner, 2026-11-13). Sending a patch upstream then still needs
  its own commit message and a Signed-off-by, which the series does not
  carry.
- Each patch has one job and names where it is meant to land: Linux, the
  `bcm63xx-cfe` repo, or OpenWrt. When upstream takes it, the copy here is
  dropped. The build and the flake check stop on a patch that applies in
  reverse, naming it as merged upstream, so a copy cannot outlive its merge.
  The flake check `openwrt-series-applies` copies the whole OpenWrt source on
  every run; that copy is the cost of the check.
- A fix is generic or it is not made. A board check inside a shared driver is
  a sign the cause is not understood yet.
- No diagnostics, experiments or cosmetics in the series. They are tools for
  finding a cause, not part of the port.
- The bootloader stays untouched. Rescue mode is the way back at every step;
  `asus-rescue probe` proved it on this unit.

## What the port guarantees

Each guarantee names what holds it. The tests in `tests/test_rescue.py` run
in the package build; the tests in `tests/hardware` run against a router.

- An image starts from one pinned OpenWrt commit and this patch series. The
  flake check `openwrt-series-applies` applies the series to the pin, and
  `test_firmware_comes_from_the_pinned_openwrt` compares the running
  router's OpenWrt revision with `flake.lock`.
- A flash goes through the router's own rescue mode over Ethernet:
  `test_discovery_packet_matches_vendor_bytes`,
  `test_write_packet_matches_vendor_bytes` and
  `test_upload_delivers_every_byte_in_order`.
- An image whose SHA256 differs from the one stated is refused before any
  packet is sent: `test_wrong_checksum_sends_nothing`.
- A flash is reported as done only on the router's own success status:
  `test_router_rejection_is_a_failure` and
  `test_missing_flash_result_is_a_failure`.
- A failure is named: `test_router_error_is_named` and
  `test_unexpected_reply_is_reported_not_dropped`.
- A patch upstream has merged leaves the series: `openwrt-series-applies`
  stops on it, and the `merged` case of `openwrt-apply-series-fixtures`
  holds that rule.
- The services the image adds change nothing until configured: `pbr` and
  `sqm-scripts` ship switched off, held by
  `test_added_service_ships_switched_off`. `adblock` ships with
  `adb_enabled` off and `https-dns-proxy` with no resolver and its forced
  DNS and canary domains off, held by `test_dns_services_ship_switched_off`;
  the `openwrt-shipped-defaults` check fails when upstream changes either
  default under them. `miniupnpd` ships with `enabled` off, held by
  `test_added_service_ships_switched_off`, and `qosify` with its WAN
  interface and device disabled, held by `test_qosify_ships_shaping_nothing`.
- A transmit power set for a radio caps every chain in its firmware:
  `test_configured_transmit_power_caps_every_chain`.

## Hardware facts (this unit, stock boot log and dumps, 2026-11-10)

- SoC BCM4906, 2x Cortex-A53 at 1.8 GHz, 512 MiB RAM, CFE 1.0.1.0.
- NAND: Macronix 256 MiB, SLC, 128 KiB blocks, 2 KiB pages, BCH-4.
- Flash map: `cferom`/NVRAM 0x0-0x100000; firmware slots 0x100000-0x6000000
  and 0x6000000-0xbf00000; misc1 0xbf00000 (8 MiB); misc2 (jffs)
  0xc700000 (47 MiB); misc3 0xf600000 (1 MiB); data 0xf700000 (8 MiB); the
  last 1 MiB holds the bad block table. One bad block at 0x2d20000.
- Radios: two 4x4 BCM4366-family chips, 2.4 GHz (device 0x43c4) on PCIe
  core 0 and 5 GHz (0x43c5) on core 1; core 2 has no link. Source: the
  unit's NVRAM `devpath0=pcie/0/1`, `devpath1=pcie/1/1`, `0:devid`,
  `1:devid`, `0:aa2g`, `1:aa5g`.
- Radio calibration: per unit, in the `data` partition (0xf700000), a JFFS2
  starting 3.2 MiB in, file `.kernel_nvram.setting`, NUL-separated
  `key=value`; radio keys carry `0:` and `1:` prefixes. Country E0, regrev
  962.
- Transmit chains and beamforming, read from the radio firmware
  (2026-11-12): 2.4 GHz transmits on three chains (`txchain` 0xb, NVRAM
  `0:sw_txchain_mask=0xb`), 5 GHz on four (0xf), and both have
  beamforming on (`txbf` 1).
- Antenna gain, from FCC ID MSQ-RTACHN00, whose model letter of
  2017-04-13 names the RT-AC86U and RT-AC2900 among identical models:
  1.33 dBi at 2.4 GHz, 1.57 dBi at 5.2 GHz and 1.85 dBi at 5.8 GHz (RF
  exposure report 1720225R-RF-US-Exp). The second-source antennas filed
  in 2019 measure 1.25 to 1.29 dBi at 2.4 GHz and 1.58 to 1.60 dBi at
  5 GHz.
- Uncapped, the firmware targets 16.5 dBm per chain at 2.4 GHz and
  14.5 dBm at 5 GHz (`txpwr_target_max`). A transmit power set through
  nl80211, as `iw dev <ap> set txpower fixed` or LuCI does, caps every
  chain's target at that value: caps of 14 and 10 dBm read back as 14
  and 10 on each chain, and `auto` restores the uncapped targets
  (2026-11-12).
- MAC layout, as offsets from the base MAC at `cferom` 0x106a0 (checked
  against the label): LAN, WAN and 2.4 GHz base+0, 5 GHz base+4.
- RAM does not survive a warm reset: a pattern written to the reserved
  region at 0x17f10000 read back with half its bits flipped after
  `reboot` (test module, 2026-11-10). A crash log has to live in flash.
- The front 2.4 GHz and 5 GHz LEDs hang off GPIO 9 of each radio, not the
  SoC: stock NVRAM `led_2g_gpio` and `led_5g_gpio` are 255 and both radios
  carry `ledbh9=0x7`, so the radio firmware drives them. The firmware
  takes their duty cycle as the `leddc` iovar at runtime (upper half on
  time, lower half off time) and rejects the generic LED ioctls
  (2026-11-12).
- The BCM7038-style watchdog resets the whole SoC: with procd's pings
  stopped the unit rebooted about 25 s later (2026-11-12).
- Before patch 0021, about one boot in five to seven, cold or warm, failed
  inside the first probe of the `brcm-sf2` switch driver, before userspace
  (boot-LED checkpoints and misc3 records, 2026-11-10 to 12). With 0021
  one warm boot in 78 came back more than 110 s after going down
  (2026-11-12), a measure that misses a crash the watchdog recovers
  sooner. Counted by misc3 records instead, 8 of 90 warm resets of image
  49af869, which carries 0021, went through a crashed boot before coming
  up (2026-11-13, 30 each of `reboot`, a stopped watchdog and a
  deliberate panic). Every record shows the same
  synchronous external abort, ESR 0x96000210, and the seven readable ones
  name `bcm_sf2_crossbar_setup+0x10`. That is the read of `REG_CROSSBAR`,
  offset 0xc8 in the switch's `reg` block, and the first access to that
  block after `bcm_sf2_sw_rst()` resets the chip with `EN_CHIP_RST`. The
  kernel panics, and the watchdog brings the unit back. Some records come
  out garbled in flash. Patch 0023 sleeps 20 ms after that reset on the
  BCM4908: with it, 90 warm resets of the same kinds left no crash record,
  while each of the 30 deliberate panics among them left its own
  (2026-11-13). Cold boots have not been counted with it. Without 0021
  but with 0023, 90 warm resets of the same kinds, rotated through idle,
  CPU, network and Wi-Fi load, left no crash record either (2026-11-13 and
  14), so 0023 is what stops the crash; without 0021 the switch is probed
  and reset three times per boot instead of once, which
  `test_switch_is_reset_once_per_boot` refuses, so 0021 stays.
- A plain `reboot` took about 50 s from the command to the next kernel,
  against about 6 s for a watchdog reset (2026-11-13). At shutdown procd
  points its stdio at `/dev/ttyS0` instead of `/dev/console` and kills
  the console login; the hangup runs `bcm_uart_shutdown()`, which turns
  the console UART's transmitter off, and every console character then
  waits out the 10 ms timeout in `wait_for_xmitr()` with interrupts off.
  One shutdown traced that way logged NAND command timeouts, squashfs
  read errors and a failed UBI write before a soft lockup panic. Patch
  0024 keeps the console port transmitting: with it a `reboot` reached
  the next kernel 16 s after the command, and five reboots in a row came
  back with no crash record.
- Stock CFE RAM stage: `cferam.005`, 361932 bytes, image version HND3221458,
  SHA256 6427360d...4b12. It differs from the GT-AC5300 one in
  `bcm63xx-cfe` (355110 bytes).

## The pieces, where each lives, where it goes

The table covers the pieces carried by patches 0001 to 0006 and
[`openwrt/cferam.nix`](../openwrt/cferam.nix). The whole series is the patch
files in [`openwrt/patches`](../openwrt/patches), applied in file-name order.

| # | Piece | Lands in | Notes |
|---|---|---|---|
| 1 | DT binding `asus,rt-ac86u` | Linux `brcm,bcmbca.yaml` | Required before the DTS. |
| 2 | `bcm4906-asus-rt-ac86u.dts` | Linux `arch/arm64/boot/dts/broadcom/bcmbca` | Written fresh from the stock DTB and the facts above, in upstream style: LED `color`/`function`, MAC as an nvmem cell in `cferom` at 0x106a0. Carried here as a `patches-6.18` patch until merged. |
| 3 | PCIe nodes for BCM4908 | Linux `bcm4908.dtsi` | The driver supports `brcm,bcm4908-pcie` in 6.18; the SoC tree has no controller nodes, so no bcm4908 board has Wi-Fi upstream. Generic: GT-AC5300 and R8000P gain it too. |
| 4 | PCIe and Wi-Fi in the target | OpenWrt `target/linux/bcm4908` | Kernel config with `pcie-brcmstb` built in; `DEVICE_PACKAGES` with `kmod-brcmfmac`, `brcmfmac-firmware-4366c0-pcie`, `wpad-basic-mbedtls`. |
| 5 | Board CFE RAM | `openwrt/bcm63xx-cfe` as `asus,rt-ac86u/cferam.000` | Extracted from the official ASUS 386_52334 image by a pinned, hashed fetch; the backup is the cross-check, not the source. |
| 6 | Device entry | OpenWrt `image/Makefile`, `platform.sh`, `board.d/02_network` | `bcm4908img`, `bcm4908asus`, ASUS product ID and firmware numbers, LAN/WAN ports. |
| 7 | Radio calibration | OpenWrt `base-files/lib/preinit/81_brcmfmac_nvram` | After the overlay mounts and before modules load, the hook mounts `data` read-only and writes the `devpath` and numbered keys as the board NVRAM, once; brcmfmac's multi-radio format picks each radio by PCIe domain. A firmware hotplug hook cannot work here: brcmfmac requests the board NVRAM without the user-mode fallback, so procd never sees the request. |
| 8 | Flash partition fix | Linux or OpenWrt pending, see openwrt/openwrt#26197 | The cfe-bootfs parser error on the inactive slot is fatal since 6.12. Fixed at its cause, for every bcm4908 board. |

## Left out of the reference fork, and why

Read from `5ocworkshop/openwrt` at `rtac86u-25.12.6`; used as a map of the
problems, not as code to copy.

- 403, 404, 405, 406, 408, 410, 426: boot-LED diagnostics and waypoints.
- 412, 424, 874: experiments; 874 showed no difference in the author's own
  tests.
- 872: Wi-Fi LED duty cycle, cosmetic and board-gated in a shared driver.
- 875: replays ASUS iovars at AP start and hard-codes country `CA`; kept as
  evidence of what the 2.4 GHz radio needs, to be solved generically or not
  at all.
- 425: board-gated PCIe "Merlin compatibility" window writes; tried only if
  the plain driver fails, and then fixed in the driver for the SoC.
- procd 910: a generic firmware-loader fix. This port hit the bug, and the
  series carries its own smaller fix for the same fault,
  [`0009-procd-abort-a-firmware-request-that-cannot-be-served.patch`](../openwrt/patches/0009-procd-abort-a-firmware-request-that-cannot-be-served.patch),
  shaped to go to procd on its own.

## Verification ladder

Each step is done and recorded before the next starts.

1. The image builds from the pinned tree with the series applied.
2. `asus-rescue flash` writes it; the router boots and answers SSH.
3. Ethernet: each port's link and its label; LAN and WAN traffic.
4. LEDs, buttons, USB.
5. PCIe links up on cores 0 and 1; both radios probe in brcmfmac.
6. Access point on each band; clients hold association and traffic.
7. `sysupgrade` to a second build.

The Firmware workflow, which runs step 1 on a GitHub runner, is outside the
set of workflows the fleet watch requires to be green, so its failure surfaces
only through the issue its report job opens.

## Decisions (maintainer, 2026-11-10)

- The DTS is written to Linux's standard, binding first, and carried here as
  a kernel patch; OpenWrt references it like every other bcm4908 board.
- Radio calibration is read at boot from the unit's own NVRAM in flash, never
  shipped as a file from one unit.
- The series stays private for now; it is still shaped for upstream, so the
  choice stays open.
- The way back to stock firmware is not exercised: the unit is not meant to
  run the ASUS firmware again, and rescue mode itself is proven by flashing
  OpenWrt through it.
- The old ASUS partitions (`misc1`, `misc2`, `misc3`) may be taken over,
  safely, with the 2026-11-10 flash backup as the copy; `cferom` and
  `data` stay untouched. `misc3` holds the kernel's panic records.

## Decisions (maintainer, 2026-11-12)

- The repository is public. The series stays shaped for upstream, so sending
  it upstream remains open.
- The image carries the kernel modules a router behind another router is
  expected to need, because none can be added after flashing: WireGuard for
  a VPN, cake with `sqm-scripts` against bufferbloat, `pbr` to send chosen
  devices through a tunnel, and the USB-serial drivers common Zigbee and
  Thread dongles use. Building every module and publishing them as a signed
  feed was left out: more build time and a signing key to keep, for modules
  nobody has asked for yet.
- The image also carries `https-dns-proxy` and `adblock` with their LuCI
  pages (2026-11-13). A flash keeps a service's settings but drops what
  `apk` installed, and after one flash `dnsmasq` still forwarded to a
  proxy that was gone, so the router had no DNS, not even to reinstall
  it. Both ship switched off through `openwrt/files`, OpenWrt's custom
  files, so a fresh install changes nothing until configured. Reinstalling
  after every flash and OpenWrt's attended sysupgrade, which builds images
  only for boards OpenWrt itself supports, were left out.
- The image also carries UPnP (`miniupnpd-nftables`) for game consoles,
  `qosify` for traffic priority, LuCI's dashboard and its Material theme
  (2026-11-13). `qosify` needs `kmod-sched-bpf` and `kmod-sched-flower`,
  which only the image can bring, and an eBPF program, which compiles
  with the LLVM nixpkgs puts in the build environment
  (`CONFIG_BPF_TOOLCHAIN_HOST`): a git build has no prebuilt BPF
  toolchain, and building LLVM inside OpenWrt costs hours. `qosify` and
  `sqm-scripts` each attach cake to the WAN, so switching `qosify` on
  means switching `sqm` off.
