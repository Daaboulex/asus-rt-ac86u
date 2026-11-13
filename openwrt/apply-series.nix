{ pkgs }:
pkgs.writeShellApplication {
  name = "openwrt-apply-series";
  runtimeInputs = [
    pkgs.coreutils
    pkgs.gnused
    pkgs.patch
  ];
  text = ''
    if [ "$#" -ne 1 ]; then
      echo "usage: openwrt-apply-series <patch directory>, run from the root of an OpenWrt tree" >&2
      exit 2
    fi
    shopt -s nullglob
    series=("$1"/*.patch)
    if [ "''${#series[@]}" -eq 0 ]; then
      echo "no patch in $1" >&2
      exit 1
    fi

    declare -A boards=()
    for change in "''${series[@]}"; do
      name=$(basename "$change")
      hunks=$(sed -n '/^@@ /p' "$change")
      if [ -z "$hunks" ]; then
        echo "has no hunk, so it changes no file content, drop it or give it one: $name" >&2
        exit 1
      fi
      if patch -p1 -R --dry-run --silent --force --fuzz=0 < "$change" > /dev/null; then
        echo "merged upstream, drop it from the series: $name" >&2
        exit 1
      fi
      echo "applying $name"
      if ! applied=$(patch -p1 --forward --no-backup-if-mismatch --fuzz=0 < "$change"); then
        printf '%s\n' "$applied"
        echo "does not apply to this OpenWrt tree without fuzz, rebase it: $name" >&2
        exit 1
      fi
      printf '%s\n' "$applied"
      if grep -q '(offset [0-9]* lines\?)' <<< "$applied"; then
        echo "applies off its hunk header, restate the hunk at the line it applies: $name" >&2
        exit 1
      fi
      touched=$(sed -n 's|^+++ b/||p' "$change")
      while IFS= read -r path; do
        if [[ "$path" =~ ^target/linux/([^/]+)/ ]] && [ "''${BASH_REMATCH[1]}" != generic ]; then
          boards[''${BASH_REMATCH[1]}]=1
        fi
      done <<< "$touched"
    done

    kernel_built() {
      local makefile="target/linux/$1/Makefile" subtarget overridden built
      for subtarget in target/linux/"$1"/*/target.mk; do
        overridden=$(sed -n '/KERNEL_PATCHVER/p' "$subtarget") || return 1
        if [ -n "$overridden" ]; then
          echo "$subtarget sets KERNEL_PATCHVER, and only $makefile is read here" >&2
          return 1
        fi
      done
      built=$(sed -n 's/^KERNEL_PATCHVER:=//p' "$makefile") || return 1
      if [[ ! "$built" =~ ^[0-9]+\.[0-9]+$ ]]; then
        echo "cannot read exactly one KERNEL_PATCHVER from $makefile" >&2
        return 1
      fi
      printf '%s\n' "$built"
    }

    versioned='^target/linux/([^/]+)/(patches|config|backport|pending|hack)-([0-9]+\.[0-9]+)(/|$)'
    for change in "''${series[@]}"; do
      name=$(basename "$change")
      touched=$(sed -n 's|^+++ b/||p' "$change")
      while IFS= read -r path; do
        if [[ "$path" =~ $versioned ]]; then
          targeted=''${BASH_REMATCH[3]}
          if [ "''${BASH_REMATCH[1]}" = generic ]; then
            against=("''${!boards[@]}")
          else
            against=("''${BASH_REMATCH[1]}")
          fi
          if [ "''${#against[@]}" -eq 0 ]; then
            echo "targets kernel $targeted through $path, but the series touches no board target to read the kernel version from: $name" >&2
            exit 1
          fi
          for target in "''${against[@]}"; do
            if ! built=$(kernel_built "$target"); then
              echo "the kernel version $target builds is unknown, and $path depends on it: $name" >&2
              exit 1
            fi
            if [ "$targeted" != "$built" ]; then
              echo "targets kernel $targeted through $path, but $target builds kernel $built, so the build would not read it; move it to $built: $name" >&2
              exit 1
            fi
          done
        fi
      done <<< "$touched"
    done
  '';
}
