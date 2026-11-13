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
  when any chain's target exceeds the configured transmit power. On
  2026-11-13 that test found both radios uncapped after a fresh boot:
  OpenWrt sets the power before it brings the interface up, and
  `brcmfmac` refused it there with `-EIO`, logged as `command failed: I/O
  error (-5)`, so the cap had only held after a Wi-Fi restart. Patch
  `884-wifi-brcmfmac-apply-a-transmit-power-set-before-bring-up` keeps the
  request and sends it to the firmware when the interface comes up. With
  it, the test passed after a fresh boot on 2026-11-13, every chain of
  both radios read 9 dBm, and the boot log held no such error.
- The access points run WPA2 with optional protected management frames, not
  WPA3. In Linux 6.18.62 an access point gets
  WPA3 (SAE) only through firmware offload, which `brcmfmac` enables when
  the firmware reports both `idauth` and `sae`; it has no user-space SAE
  for access points. On firmware 10.28.2 `iw phy` lists neither SAE
  offload nor the access point handshake offload that `idauth` brings.
  ASUS's own firmware does not offer WPA3 on this model either. Its
  newest radio firmware, 10.10.122.20 inside `dhd.ko` of release
  3.0.0.4.386.52334, carries `mfp` but not `sae` among its build tags. The
  image ships no hostapd, its `nas` and `eapd` authenticators hold no SAE
  code, and its `rc` never declares the `wpa3` capability its web pages
  check for. This was read from the image's files on 2026-11-13, not by
  running it. No public firmware for the chip carries SAE either. On
  2026-11-13 the 4366c0 builds in linux-firmware (10.28.2, 2018), Netgear
  R8000P 1.4.4.94 (10.10.131.34, 2021) and TP-Link Archer C2300 V1 2.2.1
  (10.10.122.308, built 2025-09-25) all lacked the `sae` build tag. The
  Archer C2300 V2, whose notes mention WPA3, is a MediaTek design. Asked
  for WPA2/WPA3 mixed, hostapd started and the firmware's beacon offered
  only PSK-SHA256. Since repo patches 0027 to 0029 the radios declare the
  AKMs they offer, and the wifi scripts refuse such a network with
  `AKM_NOT_SUPPORTED` instead of starting one no client can join.
- Protected management frames (802.11w) work, optional, on every network.
  The firmware builds the RSN element of beacons and probe responses
  itself from what brcmfmac passes, hostapd sends its own in message 3 of
  the 4-way handshake, and a client aborts with reason 17 when the two
  differ by a byte, which phones report as a wrong password. A handshake
  trace on 2026-11-13 showed two differences. hostapd left out the
  BIP-CMAC-128 management cipher field the firmware always writes, which
  hostapd patch `990-AP-write-the-default-management-group-cipher-into-the-RSNE`
  now writes. Given PSK and PSK-SHA256 with PMF, the firmware advertises
  only PSK-SHA256, so brcmfmac patch
  `885-wifi-brcmfmac-report-the-AKM-suites-an-access-point-offers`
  declares the AKMs the firmware advertises as given and the wifi scripts
  offer WPA-PSK alone. A Linux client then joined with `MFP:yes`, and with
  its own PMF off with `MFP:no`.
- Each access point takes an address the scripts derive from the radio's
  own one, and a rebuild that re-adds only one of a radio's networks can
  hand the networks each other's addresses. A bridge address must lie
  outside that range, or a network on one bridge can carry the other
  bridge's address. Setting `macaddr` on an access point does not help.
  The radio's own address is held by the driver's default interface, so
  netifd refuses it as "in use". After many networks are added and
  removed, the firmware also refused a derived address with
  `brcmf_c_set_cur_etheraddr: Setting cur_etheraddr failed, -52` until
  the router restarted. A full `wifi down` and `wifi up` gave every
  network the same address each time.
- A radar (DFS) channel cannot carry an access point. `brcmfmac` announces
  DFS offload but never reports the channel availability check starting or
  finishing, so hostapd cannot finish starting the access point. On
  2026-11-13, in two runs on channel 52, hostapd did not reach that check:
  its neighbour scan (`HT_SCAN`) was still running after 90 s, while on
  channel 36 it ends within 3 s.
  In Linux 6.18.62, `brcmfmac` sets `NL80211_EXT_FEATURE_DFS_OFFLOAD`
  whenever the firmware has 802.11h, calls neither `cfg80211_cac_event`
  nor `cfg80211_radar_event`, and leaves the firmware's `DFS_AP_STOP` and
  `DFS_AP_RESUME` events unhandled. Marking the check done in hostapd
  instead would transmit on a radar channel without proof of the check.
  `test_access_point_starts_on_a_radar_channel` is expected to fail, and
  fails the suite the day it passes.
- Routing runs on the CPU: OpenWrt has no hardware NAT offload for this SoC.
  No test in this repository measures throughput.
- A device that moves from behind a switch port to the router's Wi-Fi
  stays unreachable through that port for minutes. The `b53` and
  `bcm_sf2` drivers do not set `assisted_learning_on_cpu_port` (Linux
  6.18.60, and mainline in 2026-11), so the switch chip never learns that
  a Wi-Fi client sits behind the CPU and keeps the port it last saw the
  client on. On 2026-11-13, with LAN1 cabled into the upstream router's
  network and the router's own DHCP off, a client moved from that
  network's Wi-Fi to this router's got no DHCP answer for about ten
  minutes: the upstream offer came in on LAN1, `bridge fdb show` still
  listed the client on LAN1 as `self`, and the offer never reached the
  CPU. A LAN port bridged into another network invites this; a router
  that serves its own DHCP meets it only when a device moves from one of
  its LAN ports to its Wi-Fi.
- USB 3 storage reads slowly: an NVMe drive in an RTL9210 enclosure,
  linked at 5 Gbit/s under `uas`, read 35 to 44 MB/s with `dd` from the
  start of the drive, direct or cached, with the busy core waiting on
  I/O, not computing (2026-11-12 and 13). Deeper into the drive, `dd
  iflag=direct` reached 73 MB/s with 512 KiB requests and 78 MB/s with
  4 MiB, and a 4 KiB request took 0.17 ms. ASUS's firmware was reviewed
  at about 104 MB/s of USB 3 reads on this model. Under `usb-storage`
  instead of `uas` the enclosure failed `Read Capacity`. The cause is not
  known; the same drive has not been read on another host.
- A change rolled back by `uci apply` is restored in RAM first and reaches
  flash with the kernel's write-back, up to about 35 s later
  (`dirty_expire_centisecs` 3000, `dirty_writeback_centisecs` 500). On
  2026-11-12 a deliberate panic 31 s after a rollback brought the rejected
  firewall rule back at the next boot.
- The CPU temperature comes from a sensor in the CPU cluster's
  configuration block, register 0x810621a0. The vendor's GPL thermal
  driver reads its low 10 bits as (4133500 - 4906 * raw) / 10
  millidegrees, and patch
  `105-thermal-broadcom-add-a-bcm4908-thermal-sensor-driver` reports it
  the same way, as the thermal zone `cpu-thermal`, also shown in hwmon as
  `cpu_thermal`, which LuCI's dashboard files under CPU. On 2026-11-13 it
  read 66.0 C idle, 69.4 C after 10 s and 71.4 C after 60 s on all four
  cores, and 66.0 C again a minute later
  (`test_cpu_temperature_rises_under_load`). The radios report no
  temperature.
- A crash log cannot live in RAM, because the unit's RAM does not survive a
  reset; the measurement is under "Hardware facts" in
  [`DESIGN.md`](./DESIGN.md). The kernel keeps its panic records in flash, on
  the vendor partition `misc3`: `test_panic_records_go_to_misc3` and
  `test_a_panic_reboots_and_leaves_a_record`. `misc3` holds 16 records of
  64 KiB, and a panic can only write into an empty one, because nothing
  can be erased during a panic (`mtdpstore.c`); a record's space comes
  back only when its file is deleted from `/sys/fs/pstore`. Nothing on
  the router deletes them yet, so after 16 panics a new one leaves no
  record. On 2026-11-13 the store was full and lost a panic; the 15 old
  records were copied off and deleted.
- A kernel module cannot be added after flashing. OpenWrt's package feed
  builds its modules against its own kernel build, and `apk` hides every one
  of them on this image: on 2026-11-12 the image's kernel package was
  `6.18.60~b63c2fab` and the feed's `6.18.60~868fdef7`, and
  `apk add --simulate kmod-wireguard` answered "no such package", while
  `iperf3`, which has no kernel module, installed. The image therefore
  carries WireGuard, the cake shaper with `sqm-scripts`, `qosify` with its
  `sched-bpf` and `sched-flower` modules, `pbr`, `iperf3` and the
  USB-serial drivers `cp210x`, `ch341` and `cdc-acm`, held by
  `tests/hardware/test_modules.py`.
- A firmware update keeps a service's settings but drops a package added
  with `apk`. On 2026-11-13 a flash kept `https-dns-proxy`'s and
  `adblock`'s settings and removed both packages: `dnsmasq` still
  forwarded only to the proxy's port, the router had no DNS, and `apk`
  could not fetch the packages back until the forwarding was undone by
  hand. The image therefore carries both, switched off until configured
  (`test_dns_services_ship_switched_off`).
- `https-dns-proxy`'s forced DNS can come up rejecting queries instead of
  redirecting them. The proxy decides once, as it starts, from whether
  anything listens on port 53. With `adblock`'s lists loaded, `dnsmasq`
  took about 7 s to listen again after a restart. On 2026-11-13 the proxy
  restarted inside that gap, and a device asking 1.1.1.1 directly got no
  answer at all. A `redirect` in `/etc/config/firewall` (`src_dport 53`,
  `target DNAT`, `family any`) and a `rule` rejecting port 853, with the
  proxy's `force_dns` off, intercept the same queries with nothing decided
  at start.
- Rescue mode answers at 192.168.1.1 on a LAN port only, directly, through a
  switch, or over Wi-Fi bridged to it. It serves no web page.
  `asus-rescue probe` found it this way on the unit.

## Measured on the unit

Each figure names how it was taken, on 2026-11-12 and 13, with both
radios capped at 9 dBm per chain.

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
- Upload lag behind an upstream modem: two parallel `curl` uploads from the
  router saturating the line raised the ping to 1.1.1.1 from about 15 ms
  to 5 s on average and 14 s at worst. Cake from `sqm-scripts` on `wan`,
  shaping the upload at about 90 % of the measured line rate with
  `linklayer ethernet` and `overhead 34`, held it at 15 to 16 ms, 28 ms at
  worst, for about 12 % less upload throughput. A saturating download
  raised the ping by about 13 ms unshaped, so the download is left
  unshaped. Routed through the router's NAT from a laptop on its 5 GHz,
  a saturating upload kept the ping at 16.7 ms on average against 16.9 ms
  idle, so the shaping holds for forwarded traffic too. `qosify` in place
  of `sqm-scripts`, at the same rate with `overhead_type manual`,
  `overhead 34`, `noatm` and `diffserv4`, held a wired client at 14.8 to
  16.1 ms on average under a saturating upload across three runs on
  2026-11-13, against 15.0 ms for `sqm-scripts` the same hour, while
  sorting traffic into four priority tins.
- Wi-Fi to the router itself, from a laptop on 5 GHz at -45 dBm with an
  866 Mbit/s link, `iperf3 -P 4` against `iperf3 -s` on the router: 644
  Mbit/s from the laptop and 544 Mbit/s to it, with both cores about 60 %
  busy. Moving the 5 GHz radio's interrupt to core 1
  (`/proc/irq/23/smp_affinity` 2) dropped the upload to 477 Mbit/s with
  core 1 at 96 %, so the interrupts stay where the kernel puts them.
- Routing load: 164 to 200 Mbit/s of download through NAT from that
  laptop kept the router about 30 % busy, and software flow offload
  (`flow_offloading` 1) changed neither the rate nor the load, so it
  stays off. No wired client has measured routing above the internet
  line yet.
- Routing and DNS through the router from a Wi-Fi 7 client on 5 GHz at
  -46 dBm with a 780 Mbit/s link, its Wi-Fi power save off (2026-11-13):
  a 100 MB download through NAT ran at the internet line's full rate, as
  on a cable that bypasses the router, and a ping to 1.1.1.1 averaged
  16.7 ms against 15.6 ms on that cable. With the client's power save
  on, the same ping averaged 44 ms. `iperf3 -P 4` against the router
  reached 409 Mbit/s from the client and 581 Mbit/s to it.
- WireGuard on the two cores, with both ends of the tunnel on the router
  (2026-11-13): two `wireguard` interfaces made in the main namespace,
  so their UDP sockets stay there on loopback, were moved into two
  network namespaces, and `iperf3` ran between those for 15 s. One TCP
  stream carried 589 Mbit/s and two carried 559 Mbit/s, with both cores
  near 100 %. Each packet is encrypted and decrypted on the same router
  here, so a tunnel with one end on it has more headroom. Cake on the
  sending side cut two streams to 367 Mbit/s when set to 2 Gbit/s, and
  held them at 193 Mbit/s when set to 200 Mbit/s.

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
