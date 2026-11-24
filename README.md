# OpenWrt for the ASUS RT-AC86U

OpenWrt for the ASUS RT-AC86U, also sold as the RT-AC2900, built from current
OpenWrt main. Upstream OpenWrt carries the router's SoC family (`bcm4908`) but
not this board, so this repository holds the board's patch series and
`asus-rescue`, a Linux tool that flashes an image through the router's own
rescue mode without opening the case. It is for someone who owns this router,
runs Linux with Nix, and is comfortable flashing firmware.

## Status

The port runs on one RT-AC86U. No second unit has been tried, and the unit's
hardware revision is not known. Read [Known limits](#known-limits) before you
flash, the Wi-Fi limits above all.

## Install

Work in a clone of this repository. Take a released image or build one, then
put it on the router through rescue mode.

### A released image

Every build of `main` is published under
[Releases](https://github.com/Daaboulex/asus-rt-ac86u/releases) as the image,
its `SHA256SUMS` and `SHA256SUMS.sig`, the signature made with the release key
whose public half is [`openwrt/release-key.pub`](openwrt/release-key.pub).
Download the three files of one release into a folder of their own, and check
the signature and the checksum from there:

```bash
nix shell 'nixpkgs#signify' -c signify -V -p <clone>/openwrt/release-key.pub -m SHA256SUMS -x SHA256SUMS.sig
sha256sum -c SHA256SUMS
```

### An image of your own

```bash
nix run .#openwrt-build -- rt-ac86u
```

The image lands in `.devshell/openwrt/bin/targets/bcm4908/generic/`. A first
build takes tens of gigabytes and runs on x86_64 and aarch64 Linux, fastest
with many cores. The image trusts the key in `openwrt/release-key.pub` as your
clone has it, so it takes this repository's releases unless you put the
public half of your own key there first (see
[Automatic updates](#automatic-updates)).

### Flash it through rescue mode

Note the image's SHA256, as `SHA256SUMS` or `sha256sum` gives it. Then:

1. Power the router off, hold Reset, power it on, and release Reset when the
   power LED blinks slowly.
2. Connect a LAN port, not the WAN port, to the same network segment as your
   machine.
3. Give your machine the address `192.168.1.10/24`:

   ```bash
   nmcli device modify <device> +ipv4.addresses 192.168.1.10/24
   ```

4. The router replies from a new port, which a host firewall drops. On NixOS,
   open one fixed port for the session, and close it again when you are done
   with `sudo nixos-firewall-tool reset`:

   ```bash
   sudo nixos-firewall-tool open udp 50069
   ```

5. Find the router without writing anything, check the plan, then flash:

   ```bash
   nix run .#default -- probe --local-port 50069
   nix run .#default -- flash <image>.bin --sha256 <sha256> --local-port 50069 --dry-run
   nix run .#default -- flash <image>.bin --sha256 <sha256> --local-port 50069
   ```

The router answers at `192.168.1.1`. The tool refuses an image whose SHA256
differs from the one you state, before it sends a packet, and reports success
only when the router does. Rescue mode belongs to the bootloader, which this
port leaves alone.

## Updating

Take a newer released image or build one, as under [Install](#install). Then
flash it from the running router with `sysupgrade`, which keeps the settings:

```bash
ssh root@192.168.1.1 'cat > /tmp/firmware.bin' < <image>.bin
ssh root@192.168.1.1 sysupgrade /tmp/firmware.bin
```

### Automatic updates

The image carries `port-update`, which follows this repository's releases and
stays off until switched on. Every build of `main` is signed by the workflow
with the release key, whose public half is `openwrt/release-key.pub` and ships
in the image, so a router trusts the releases from its first boot. A router
takes the newest release that is a few days old and newer than its own, in a
night window while the WAN is quiet. Before its first update it fetches the
release it runs, so it always holds a way back. Before flashing it notes what
works: the network interfaces that are up, the Wi-Fi networks, the WireGuard
tunnels with a recent handshake, the services procd keeps alive, DNS and a
kernel free of crashes. After the update it waits for all of them, and flashes
the previous image again when one stays missing. A release that failed is never
taken again.
An image that does not boot at all cannot go back by itself: the bootloader
offers the previous image only on its serial console, so that case needs
rescue mode.

```bash
ssh root@192.168.1.1 'uci set port_update.main.enabled=1 && uci commit port_update && port-update check'
```

The settings live in `/etc/config/port_update` on the router; the options and
their defaults are read at the top of `/usr/sbin/port-update`. Checks of your
own, for a VPN, a blocklist or a firewall rule, go into `/etc/port-update/checks/`
on the router: every executable file there is one check, passing when it exits
0 within a minute. They follow the same rule as the rest: a check that passed
before an update must pass after it. `port-update check` lists the ones failing
now, and `chmod -x` switches one off. The folder survives every update. It also
names the release the router runs, the one it waits for and the day that one
falls due.

A router takes a release signed with any key in `/etc/port-update/keys`. The
image brings the one from `openwrt/release-key.pub`; `port-update trust
<public key>` adds another and deleting its file there drops it. A router
updates itself only while it runs a published release, since that release is
its way back: after you flash an image of your own, it waits until you flash a
release by hand.

To follow releases of your own, publish them from a fork:

1. Replace the key: delete `openwrt/release-key.pub`, which signify will not
   overwrite, run `signify -G -n -p openwrt/release-key.pub -s
   release-key.sec`, and commit the new `openwrt/release-key.pub`.
2. Store the secret half as `RELEASE_SIGNING_KEY` in a repository environment
   named `release` that only `main` may use, and keep a copy off GitHub.
3. Flash one of the fork's releases onto each router and set
   `port_update.main.url` to the fork's releases address,
   `https://api.github.com/repos/<owner>/<repository>/releases`.

A router trusts only the keys its image carries, so changing the key later
means flashing each router once by hand with an image that carries the new
one.

## Keeping a device local

Add a device's MAC address to the IP set `isolated` in LuCI, under
Network, Firewall, IP Sets, or from a shell:

```bash
ssh root@192.168.1.1 'uci add_list firewall.isolated.entry=<mac> && uci commit firewall && fw4 reload'
```

The device keeps its address and answers what another device starts, over
IPv4, and reaches nothing else: not the internet, not DNS, not the router,
not another device. Frames that carry no IP, such as ARP and the Wi-Fi key
handshake, still pass. A connection it opened before is cut. Set the device up
in its own app first, while it can still reach its vendor's servers.

## Testing on the router

`hardware-test` checks a running router over SSH, one test per behaviour the
port promises. `ROUTER` names the router:

```bash
ROUTER=192.168.1.1 nix run .#hardware-test
```

The tests log in as root with a key, never a password; `ROUTER_IDENTITY`
names the key file when it is not one of ssh's defaults.

Three switches open the tests that need more than a look:

| Variable | Opens |
|---|---|
| `ROUTER_DISRUPTIVE=1` | brief outages: WAN down and up, a band off and on, a radar channel, a firewall change left to roll back |
| `ROUTER_GUIDED=1` | steps that need hands or eyes: buttons, cables, LEDs, USB ports, failsafe |
| `ROUTER_DESTRUCTIVE=1` | a deliberate panic, repeated reboots, a factory reset restored from a fresh backup, a sysupgrade to `ROUTER_IMAGE`, and two automatic updates to it, the second losing a check and going back |

## Known limits

- The radios run Broadcom's closed firmware; no open firmware exists for them.
- The radios do not run on a country's limits, the EU's included: their
  firmware runs Broadcom's worldwide locale and ignores the country set on
  the router. A transmit power of 9 dBm on each radio keeps them within the
  EU's limits.
- A radar (DFS) channel cannot carry an access point.
- On 5 GHz the radio firmware that offers WPA3 sends beacons and every
  frame at a legacy rate far weaker than its fast data, so a distant
  client may find the 5 GHz networks late; `docs/COMPATIBILITY.md` lists
  what was measured and ruled out.
- There is no hardware NAT offload; routing runs on the CPU.
- The radios report no temperature. The CPU does.
- Rescue mode answers on a LAN port only, and serves no web page.
- A kernel module cannot be installed from OpenWrt's package feed. The image
  carries WireGuard, the cake shaper, `qosify` traffic priority, UPnP and
  three USB-serial drivers, switched off until configured.
- A firmware update keeps settings but drops packages added with `apk`. The
  image therefore carries encrypted DNS (`https-dns-proxy`) and ad blocking
  (`adblock`), switched off until configured.

The detail and the evidence for each are in
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Getting back in

Try these in order, lightest first.

1. A change cut your access. Wait. LuCI's Save & Apply, and
   `ubus call uci apply` with `rollback`, restore the old settings unless the
   change is confirmed from a working connection before the timeout.
2. You cannot get past the settings or the password. Hold Reset until the
   power LED blinks fast, about 5 s, then let go. The router wipes its
   settings and comes back with its first-boot settings and no root password.
   `sysupgrade -b <file>` makes a backup beforehand and `sysupgrade -r <file>`
   restores it.
3. The settings stop the boot. Reboot and, from the moment the power LED
   starts blinking, tap the LED button about twice a second for 10 s. The
   router comes up as `OpenWrt-failsafe` on LAN1 only, at `192.168.1.1`, with
   no password and the settings untouched on flash. Tap the LED button, not
   another one: a press after that window only turns the LEDs off, and the
   next press turns them back on.
4. The firmware no longer boots. Use rescue mode, as under
   [Flash it through rescue mode](#flash-it-through-rescue-mode).

## More

- [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md): the unit, the known limits
  and their evidence.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): the dev shell, how the image is
  built, what each stage of an update proves, and the release key.
- [docs/DESIGN.md](docs/DESIGN.md): how the port is built, what it
  guarantees, and the hardware facts read from the unit.
- [docs/UPSTREAMING.md](docs/UPSTREAMING.md): where each patch would go
  upstream and what a submission still needs.
- [CHANGELOG.md](CHANGELOG.md)

## License

MIT. See [`LICENSE`](./LICENSE).
