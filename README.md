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

Work in a clone of this repository. Build the image first:

```bash
nix run .#openwrt-build -- rt-ac86u
```

The image lands in `.devshell/openwrt/bin/targets/bcm4908/generic/`. A first
build takes tens of gigabytes and runs best on a many-core x86_64 machine.
Note the image's SHA256, as `sha256sum` prints it.

Then put the image on the router through rescue mode:

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

Build the new image the same way. Then flash it from the running router with
`sysupgrade`, which keeps the settings:

```bash
ssh root@192.168.1.1 'cat > /tmp/firmware.bin' < <image>.bin
ssh root@192.168.1.1 sysupgrade /tmp/firmware.bin
```

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
| `ROUTER_DESTRUCTIVE=1` | a deliberate panic, repeated reboots, a factory reset restored from a fresh backup, and a sysupgrade to `ROUTER_IMAGE` |

## Known limits

- The radios run Broadcom's closed firmware; no open firmware exists for them.
- The radios do not run on German or EU limits: their firmware runs
  Broadcom's worldwide locale and ignores the country set on the router.
  A transmit power of 9 dBm on each radio keeps them within those limits.
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
   [Install](#install).

## More

- [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md): the unit, the known limits
  and their evidence.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): the dev shell, how the image is
  built, and what each stage of an update proves.
- [docs/DESIGN.md](docs/DESIGN.md): how the port is built, what it
  guarantees, and the hardware facts read from the unit.
- [CHANGELOG.md](CHANGELOG.md)

## License

MIT. See [`LICENSE`](./LICENSE).
