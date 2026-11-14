{
  description = "OpenWrt port and Linux rescue-mode flasher for the ASUS RT-AC86U and RT-AC2900";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    git-hooks = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    std = {
      url = "github:Daaboulex/nix-packaging-standard/release";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.git-hooks.follows = "git-hooks";
    };
    openwrt = {
      url = "github:openwrt/openwrt";
      flake = false;
    };
    openwrt-packages = {
      url = "github:openwrt/packages";
      flake = false;
    };
    openwrt-luci = {
      url = "github:openwrt/luci";
      flake = false;
    };
  };

  outputs =
    inputs@{ flake-parts, self, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      imports = [ inputs.std.flakeModules.base ];

      perSystem =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          applySeries = import ./openwrt/apply-series.nix { inherit pkgs; };
          seriesApplied =
            name: tree: series:
            pkgs.runCommand name { } ''
              cp -r ${tree} tree
              chmod -R u+w tree
              cd tree
              ${lib.getExe applySeries} ${series}
              touch "$out"
            '';
        in
        {
          pre-commit.settings.hooks.trim-trailing-whitespace.excludes = [ "^openwrt/patches/" ];
          pre-commit.settings.hooks.end-of-file-fixer.excludes = [ "^openwrt/patches/" ];
          pre-commit.settings.hooks.typos.settings.config.default.extend-identifiers.MODULE_PARM_DESC =
            "MODULE_PARM_DESC";
          pre-commit.settings.hooks.typos.settings.config.default.extend-identifiers.sme_state = "sme_state";
          pre-commit.settings.hooks.typos.settings.config.default.extend-identifiers.nd_enabled =
            "nd_enabled";
          pre-commit.settings.hooks.typos.settings.config.default.extend-ignore-re = [
            "(?m)^index [0-9a-f]+\\.\\.[0-9a-f]+( [0-7]+)?$"
          ];

          packages.default = pkgs.python312.pkgs.callPackage ./package.nix { };

          packages.openwrt-build = import ./openwrt/build.nix {
            inherit pkgs applySeries;
            inherit (inputs) openwrt;
            cferam = import ./openwrt/cferam.nix { inherit pkgs; };
            feeds = {
              packages = inputs.openwrt-packages;
              luci = inputs.openwrt-luci;
            };
          };

          packages.hardware-test = pkgs.writeShellApplication {
            name = "hardware-test";
            runtimeInputs = [
              (pkgs.python312.withPackages (ps: [ ps.pytest ]))
              pkgs.openssh
              pkgs.jq
              pkgs.git
            ];
            text = ''
              root=$(git rev-parse --show-toplevel)
              EXPECTED_OPENWRT_REV=$(jq -er '.nodes.openwrt.locked.rev' "$root/flake.lock")
              export EXPECTED_OPENWRT_REV
              exec pytest -p no:cacheprovider --basetemp "$root/.devshell/hardware-test-tmp" "$root/tests/hardware" "$@"
            '';
          };

          checks.python-site-packages = inputs.std.lib.pythonSitePackagesCheck {
            inherit pkgs;
            drv = config.packages.default;
            package = "asus_rescue";
          };

          checks.openwrt-series-applies =
            seriesApplied "openwrt-series-applies" inputs.openwrt
              ./openwrt/patches;

          checks.openwrt-apply-series-fixtures =
            let
              fixtures = ./tests/fixtures/apply-series;
              applied = case: seriesApplied "apply-series-${case}" (fixtures + "/tree") (fixtures + "/${case}");
              refusals = {
                rejects = "rebase it: 0001-notes-change-lines-the-tree-lacks.patch";
                fuzz = "without fuzz, rebase it: 0001-notes-add-a-line-on-loose-context.patch";
                offset = "restate the hunk at the line it applies: 0001-notes-add-a-line-off-its-header.patch";
                merged = "drop it from the series: 0001-notes-add-a-line-the-tree-has.patch";
                merged-deletion = "drop it from the series: 0001-notes-drop-a-line-the-tree-lacks.patch";
                no-hunk = "has no hunk";
                stale-board = "targets kernel 6.12 through target/linux/board/patches-6.12/100-fixture.patch, but board builds kernel 6.18";
                stale-generic = "targets kernel 6.12 through target/linux/generic/hack-6.12/900-fixture.patch, but board builds kernel 6.18";
                generic-alone = "touches no board target";
                subtarget-override = "target/linux/board/sub/target.mk sets KERNEL_PATCHVER";
                unreadable-version = "cannot read exactly one KERNEL_PATCHVER from target/linux/board/Makefile";
              };
            in
            pkgs.runCommand "openwrt-apply-series-fixtures" { } ''
              bad=0
              test -e ${applied "control"}
              echo "  ok   control: a series that fits is applied"
              ${lib.concatStrings (
                lib.mapAttrsToList (case: message: ''
                  log=${pkgs.testers.testBuildFailure (applied case)}/testBuildFailure.log
                  if grep -qF -- ${lib.escapeShellArg message} "$log"; then
                    echo "  ok   ${case}: refused"
                  else
                    echo "  FAIL ${case}: the refusal did not say: ${message}"
                    cat "$log"
                    bad=1
                  fi
                '') refusals
              )}
              [ "$bad" = 0 ] || exit 1
              touch "$out"
            '';

          checks.openwrt-shipped-defaults =
            let
              upstream = inputs.openwrt-packages;
              core = inputs.openwrt;
              ours = ./openwrt/files/etc/config;
            in
            pkgs.runCommand "openwrt-shipped-defaults" { } ''
              options() { grep -vE '^[[:space:]]*(#|$)' "$1"; }
              mainSection() { options "$1" | awk '/^config / { inside = ($2 == "main") } inside'; }
              options ${upstream}/net/adblock/files/adblock.conf \
                | sed "s/option adb_enabled '1'/option adb_enabled '0'/" > adblock.expected
              diff -u adblock.expected ${ours}/adblock
              mainSection ${upstream}/net/https-dns-proxy/files/etc/config/https-dns-proxy \
                | sed -E "s/option (canary_domains_icloud|canary_domains_mozilla|force_dns) '1'/option \1 '0'/" \
                > https-dns-proxy.expected
              diff -u https-dns-proxy.expected ${ours}/https-dns-proxy
              options ${core}/package/network/services/uhttpd/files/uhttpd.config \
                | sed -E 's/(option redirect_https\t)0/\11/' > uhttpd.expected
              diff -u uhttpd.expected ${ours}/uhttpd
              touch "$out"
            '';

          checks.lint = pkgs.runCommand "asus-rescue-lint" { nativeBuildInputs = [ pkgs.ruff ]; } ''
            export RUFF_CACHE_DIR="$TMPDIR/ruff-cache"
            cd ${self}
            ruff check src tests
            ruff format --check src tests
            touch "$out"
          '';

          devShells.default = lib.mkForce (
            inputs.std.lib.mkDevShell { inherit pkgs config; } {
              packages = [
                (pkgs.python312.withPackages (ps: [ ps.pytest ]))
                pkgs.ruff
                pkgs.nil
              ];
            }
          );
        };

      flake.overlays.default = final: _prev: {
        asus-rescue = final.python312.pkgs.callPackage ./package.nix { };
      };
    };
}
