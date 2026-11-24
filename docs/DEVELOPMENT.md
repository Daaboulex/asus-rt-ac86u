# Development: building, checks and updates

## The dev shell

```bash
nix develop
pytest
nix flake check --no-eval-cache
```

The dev shell pins every tool cache into `.devshell/` and writes nothing to
your home directory. Without `ROUTER`, `pytest` skips every hardware test.

## How the image is built

OpenWrt and its `packages` and `luci` feeds are flake inputs, so
[`flake.lock`](../flake.lock) pins the exact commits. `openwrt-build` copies
them into `.devshell/openwrt`, applies `openwrt/patches/*.patch` in file-name
order, starts from `openwrt/config/<seed>.seed`, downloads every source, then
runs `make`:

```bash
nix run .#openwrt-build -- rt-ac86u
```

Images land in `.devshell/openwrt/bin/targets/bcm4908/generic/`. A first build
takes tens of gigabytes and runs on x86_64 and aarch64 Linux, fastest with many
cores.

The build stops, naming the patch, when a patch has no hunk, does not apply,
or applies in reverse, which means OpenWrt has merged it and it has to leave
the series. It also stops when a kernel patch or kernel config in the series
sits under a kernel version other than the one its target builds.

## What each stage of an update proves

The Maintenance workflow moves `flake.lock` to the newest OpenWrt, `packages`
and `luci` commits on a schedule. Before it pushes the new pins it runs the
flake checks. `openwrt-series-applies` proves two things there: the patch
series applies to the new OpenWrt tree, and the kernel patches in it sit
under the kernel version `bcm4908` builds. A pin that fails either is
reported in an issue and never lands. `openwrt-apply-series-fixtures` holds
each refusal of that rule against a small fixture tree.

The kernel and `mac80211` patches inside the series meet their own sources
only during the image build. The Firmware workflow runs that build on a
GitHub runner after the pins have landed, so a break there shows up as a
failed Firmware run and its issue, with the pins already on `main`.

A clean Firmware run keeps the image, with a `SHA256SUMS` file, as an
artifact of the run. On `main` it then signs `SHA256SUMS` with the release
key, checks the signature against `openwrt/release-key.pub`, and publishes the
image, `SHA256SUMS` and `SHA256SUMS.sig` as the release `build-<commit>`. A
run that lacks the secret, or whose secret does not match the public half in
the repository, fails there rather than publish a release no router would
take.

No runner has a router, so a release is published without a hardware test.
What guards a router is its own updater: it takes a release only once it is a
few days old, notes what works before the update, and goes back when the
update loses any of it (README, Automatic updates). `hardware-test` against
the flashed router stays the check before a change lands, run by hand.

## The release key

The public half is `openwrt/release-key.pub`; the image build installs it as
`/etc/port-update/keys/<id>`, the name `usign` looks a key up by. The secret
half is the secret `RELEASE_SIGNING_KEY` of the repository environment
`release`, which only `main` may use; GitHub never shows it again, so the
maintainer keeps a copy off GitHub. Without the secret no release is
published, and routers keep running what they have. A new key reaches a
router only through an image that carries it, so changing the key, after a
loss or a leak, means flashing each router once by hand.

## Notes on the hardware tests

`hardware-test` reads the pinned OpenWrt revision from `flake.lock` and
compares it with the one the router runs. The factory reset test saves its
backup to `.devshell/router-backups/` before it asks for the button.

After an update, set `ROUTER_IMAGE` to the new image and run with all three
switches, so the new image is checked the same way as the last one.
