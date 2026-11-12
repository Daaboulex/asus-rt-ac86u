# Compatibility: what was tried, and the evidence

## The unit

The port is tested on one unit. Its label shows no hardware revision. NVRAM
reports `boardrev` 0x1102; how that maps to the R1.5 the reference fork was
tested on is unknown, so every hardware claim is checked on this unit. No
second unit and no other revision has been tried.

What was read from the unit, with the dates, is under "Hardware facts" in
[`DESIGN.md`](./DESIGN.md).

## Known limits

Each limit names its evidence. Where nothing in this repository measures it,
the line says so.

- The radios run Broadcom's closed firmware under the open `brcmfmac` driver;
  no open firmware exists for them. The image carries `kmod-brcmfmac` and
  `brcmfmac-firmware-4366c0-pcie`, and
  `test_both_radios_start_their_firmware` checks that both start.
- The radios do not run on German or EU limits. Both radios' firmware runs
  Broadcom's worldwide locale `XT` and ignores the country `E0` and revision
  `962` in the unit's NVRAM. `brcmfmac` passes a configured country to the
  firmware only through a `brcm,ccode-map`, which this board does not have,
  and linux-firmware ships no CLM file for the 4366c. A transmit power of
  9 dBm on each radio (`uci set wireless.radio0.txpower=9`, the same for
  `radio1`) keeps the radios within the German limits, which follow the
  EU's: 19.9 dBm EIRP at 2.4 GHz and 22.6 dBm on channels 36 to 48,
  counting the beamforming gain of three and four chains and the antenna
  gain under "Hardware facts" in [`DESIGN.md`](./DESIGN.md). On 2026-11-12
  the cap read back as 9 dBm on every chain of both radios through the
  firmware's `txpwr_target_max`. The image ships `iw-full` for that
  reading, and `test_configured_transmit_power_caps_every_chain` fails
  when any chain's target exceeds the configured transmit power.
- A radar (DFS) channel cannot carry an access point. `brcmfmac` announces
  DFS offload but never reports the channel availability check starting or
  finishing, so hostapd waits for it and never starts the access point.
  `test_access_point_starts_on_a_radar_channel` is expected to fail, and
  fails the suite the day it passes.
- Routing runs on the CPU: OpenWrt has no hardware NAT offload for this SoC.
  No test in this repository measures throughput.
- USB 3 storage reads slowly: an NVMe enclosure linked at 5 Gbit/s under
  `uas` read 37 to 42 MB/s with `dd`, direct or cached, while both cores
  stayed nearly idle (2026-11-12). The cause is not known.
- A change rolled back by `uci apply` is restored in RAM first and reaches
  flash with the kernel's write-back, up to about 35 s later
  (`dirty_expire_centisecs` 3000, `dirty_writeback_centisecs` 500). On
  2026-11-12 a deliberate panic 31 s after a rollback brought the rejected
  firewall rule back at the next boot.
- The unit reports no temperatures: Linux has no thermal driver for the
  BCM4908. No test in this repository checks it.
- A crash log cannot live in RAM, because the unit's RAM does not survive a
  reset; the measurement is under "Hardware facts" in
  [`DESIGN.md`](./DESIGN.md). The kernel keeps its panic records in flash, on
  the vendor partition `misc3`: `test_panic_records_go_to_misc3` and
  `test_a_panic_reboots_and_leaves_a_record`.
- A kernel module cannot be added after flashing. OpenWrt's package feed
  builds its modules against its own kernel build, and `apk` hides every one
  of them on this image: on 2026-11-12 the image's kernel package was
  `6.18.60~b63c2fab` and the feed's `6.18.60~868fdef7`, and
  `apk add --simulate kmod-wireguard` answered "no such package", while
  `iperf3`, which has no kernel module, installed. The image therefore
  carries WireGuard, the cake shaper with `sqm-scripts`, `pbr`, `iperf3` and
  the USB-serial drivers `cp210x`, `ch341` and `cdc-acm`, held by
  `tests/hardware/test_modules.py`.
- Rescue mode answers at 192.168.1.1 on a LAN port only, directly, through a
  switch, or over Wi-Fi bridged to it. It serves no web page.
  `asus-rescue probe` found it this way on the unit.

## Measured on the unit

Each figure names how it was taken, on 2026-11-12, with both radios capped
at 9 dBm per chain.

- Wi-Fi link to a phone, from `iw dev <ap> station dump`: 975 to
  1083 Mbit/s on 5 GHz at 80 MHz with -44 to -49 dBm of signal, and 520 to
  650 Mbit/s at -67 to -69 dBm through an outside wall; 192 Mbit/s on
  2.4 GHz at 20 MHz close by, carrying about 100 Mbit/s of TCP. Close to
  the router the internet line, not the Wi-Fi, set the speed.
- Automatic channel selection works: with `channel` set to `auto` and
  `channels` to `1 6 11`, hostapd's ACS read the firmware's busy time per
  channel and picked the least busy, which matched eight scans of
  `iw dev <ap> survey dump`. The survey carries no noise floor for
  channels 12 and 13, which ACS then skips.
- Upload lag behind a DSL modem: two parallel `curl` uploads from the
  router saturating the line raised the ping to 1.1.1.1 from about 15 ms
  to 5 s on average and 14 s at worst. Cake from `sqm-scripts` on `wan`,
  shaping the upload at about 90 % of the measured line rate with
  `linklayer ethernet` and `overhead 34`, held it at 15 to 16 ms, 28 ms at
  worst, for about 12 % less upload throughput. A saturating download
  raised the ping by about 13 ms unshaped, so the download is left
  unshaped.

## The ways back in

Three of the four ways back in the README are held by tests in
`tests/hardware/test_recovery.py`:
`test_unconfirmed_change_rolls_back_by_itself`,
`test_failsafe_boots_without_the_settings` and
`test_factory_reset_clears_settings_and_backup_restores_them`. The fourth,
rescue mode, has no test of its own; OpenWrt was first put on the unit
through it. Going back to the ASUS firmware through rescue mode has not been
tried.

`test_sysupgrade_keeps_settings` flashes the image named in `ROUTER_IMAGE`
with `sysupgrade` and checks that a setting written before it is still there
after the reboot.
