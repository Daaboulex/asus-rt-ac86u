# Upstreaming

This port is not being sent upstream by its maintainer. Its patches are
written in the place and form upstream expects, so anyone who wants them in
Linux, OpenWrt or the projects below can take them from here. This page says
where each one goes and what a submission still needs.

## What a submission needs

- A Signed-off-by under the submitter's own name, as the Developer's
  Certificate of Origin asks. The patches carry none. A submitter who did not
  write a patch certifies it under clause (b), keeps its author, and links
  the patch in this repository.
- A rebase onto the tree it goes to and a clean `scripts/checkpatch.pl` run
  there. On 2026-11-14 every kernel patch of the series went through the
  `checkpatch.pl` of Linux 7.4-rc2: none had an error, and the warnings left
  are a single device-tree string and comments that match the struct beside
  them.
- The recipients `scripts/get_maintainer.pl` names for the patch. Linux takes
  patches by `git send-email` to those lists, not as pull requests.
- What it was tested on: the hardware suite in `tests/hardware` and the
  measurements in [`COMPATIBILITY.md`](./COMPATIBILITY.md) say how each change
  was run on the unit.

## Order

1. Linux, one series per subsystem in the table below.
2. OpenWrt, one pull request to `openwrt/openwrt` with the device support.
   It carries the Linux patches in `target/linux/bcm4908/patches-6.18` under
   OpenWrt's numbers for pending patches until Linux merges them, and the
   brcmfmac patches in `package/kernel/mac80211/patches/brcm` the same way.
3. procd, ucode and hostapd, each on its own.

## Where each patch goes

Kernel patches are named by their number in `patches-6.18` or
`patches/brcm`; the others by their number in [`openwrt/patches`](../openwrt/patches).

| Patches | Lands in | Through | Before it can go |
|---|---|---|---|
| 310-318 | Linux `bcmbca` device tree and its binding | `devicetree` list, Broadcom SoC tree | 316's `bootargs` stay in OpenWrt's copy. |
| 710, 711 | Linux `drivers/net/dsa/bcm_sf2.c` | `netdev`, as fixes | |
| 810, 816 | Linux `pcie-brcmstb.c` | `linux-pci` | 816 needs a rebase: the BCM4908 config struct changed by 7.4. |
| 811 | Linux `leds-bcm63138.c` | `linux-leds` | |
| 812 | Linux `bcm7038_wdt.c` | `linux-watchdog` | |
| 813 | Linux `bcm63xx_uart.c` | `linux-serial` | |
| 814, 815 | Linux thermal binding and driver | `linux-pm` | The binding's maintainer entry needs an address that takes mail. |
| 880-896 | Linux `brcmfmac` | `linux-wireless`: fixes (891, 892, 895, 896) to `wireless` with Fixes tags, the rest to `wireless-next` | A rebase on `wireless-next`: 883, 885, 886 and 891 no longer apply cleanly at 7.4. |
| 001-005 in `patches/brcm` | Already in Linux 7.3 and 7.4 | Nothing to send | They leave when OpenWrt's backports include them. |
| Board bring-up | OpenWrt, as the table in [`DESIGN.md`](./DESIGN.md) lists piece by piece | `openwrt/openwrt` and `openwrt/bcm63xx-cfe` | After the Linux series are posted. |
| 0009 | procd | OpenWrt's `procd` repository | |
| 0026 | hostapd | The `hostap` list, then OpenWrt's hostapd package | |
| 0028 | ucode | The ucode repository | |
| 0029 | wifi-scripts | `openwrt/openwrt` | |
| 0036 | Stays here | | A vendor GPL drop from a mirror; linux-firmware takes Broadcom firmware from Broadcom only. |
| Image defaults (packages, LuCI over HTTPS) | Stay here | | Product choices, not device support. |
