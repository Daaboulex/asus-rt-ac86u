{
  pkgs,
  openwrt,
  feeds,
  cferam,
  applySeries,
}:
let
  feedArgs = pkgs.lib.concatMapStringsSep " " (name: "${name} \"$work/feed-src/${name}\"") (
    builtins.attrNames feeds
  );
  feedCopies = pkgs.lib.concatStrings (
    pkgs.lib.mapAttrsToList (name: src: ''
      rsync -a --no-owner --no-group --delete --chmod=u+w "${src}/" "$work/feed-src/${name}/"
    '') feeds
  );
  ltoPlugin = "${pkgs.gcc.cc}/libexec/gcc/${pkgs.stdenv.hostPlatform.config}/${pkgs.gcc.cc.version}/liblto_plugin.so";
  ltoTools = pkgs.runCommand "lto-binutils" { } ''
    test -f ${ltoPlugin}
    mkdir -p "$out/bin"
    for tool in ar nm ranlib; do
      printf '#!${pkgs.runtimeShell}\nexec ${pkgs.binutils-unwrapped}/bin/%s --plugin ${ltoPlugin} "$@"\n' "$tool" > "$out/bin/$tool"
      chmod +x "$out/bin/$tool"
    done
  '';
  prepare = pkgs.writeShellApplication {
    name = "openwrt-prepare";
    text = ''
      if [ "$#" -lt 1 ]; then
        echo "usage: openwrt-build <seed> [make arguments]" >&2
        exit 2
      fi
      root=$(git rev-parse --show-toplevel)
      seed="$root/openwrt/config/$1.seed"
      if [ ! -f "$seed" ]; then
        echo "no seed $seed" >&2
        exit 2
      fi
      shift
      work="$root/.devshell/openwrt"
      mkdir -p "$work/feed-src"
      rsync -a --no-owner --no-group --delete --chmod=u+w \
        --exclude=/build_dir/ --exclude=/staging_dir/ --exclude=/dl/ --exclude=/tmp/ \
        --exclude=/bin/ --exclude=/logs/ --exclude=/feeds/ --exclude=/package/feeds/ \
        --exclude=/feed-src/ --exclude=/.config --exclude=/.config.old --exclude=/feeds.conf \
        --exclude='/key-build*' --exclude=/private-key.pem --exclude=/public-key.pem \
        "${openwrt}/" "$work/"
      ${feedCopies}
      rsync -a --no-owner --no-group --delete --chmod=u+w "$root/openwrt/files/" "$work/files/"
      cd "$work"
      printf '%s\n' "${openwrt.shortRev}" > version
      printf '%s\n' "${toString openwrt.lastModified}" > version.date
      ${pkgs.lib.getExe applySeries} "$root/openwrt/patches"
      install -D -m 0644 ${cferam} "package/kernel/bcm63xx-cfe/files/asus,rt-ac86u/cferam.000"
      printf 'src-link %s %s\n' ${feedArgs} > feeds.conf
      ./scripts/feeds update -a
      ./scripts/feeds install -a
      cp "$seed" .config
      make defconfig
      make -j"$(nproc)" download
      make -j"$(nproc)" "$@"
    '';
  };
in
pkgs.buildFHSEnv {
  name = "openwrt-build";
  targetPkgs =
    p: with p; [
      bash
      bc
      bison
      bzip2
      coreutils
      curl
      diffutils
      elfutils
      file
      findutils
      flex
      gawk
      gcc
      getopt
      gettext
      git
      gnumake
      gnugrep
      gnused
      gnutar
      gzip
      libxslt
      ncurses
      openssl
      patch
      perl
      pkg-config
      (python3.withPackages (ps: [
        ps.setuptools
        ps.pyelftools
      ]))
      quilt
      rsync
      swig
      unzip
      util-linux
      wget
      which
      xz
      zlib
      zstd
    ];
  extraOutputsToInstall = [ "dev" ];
  profile = ''
    export NIX_HARDENING_ENABLE=""
    export FAKEROOTDONTTRYCHOWN=1
    export PATH="${ltoTools}/bin:$PATH"
  '';
  runScript = pkgs.lib.getExe prepare;
  meta = {
    description = "Build OpenWrt for the RT-AC86U from the pinned source, feeds and patch series";
    license = pkgs.lib.licenses.mit;
    mainProgram = "openwrt-build";
    platforms = pkgs.lib.platforms.linux;
  };
}
