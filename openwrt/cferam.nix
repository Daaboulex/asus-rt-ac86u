{ pkgs }:
let
  firmware = pkgs.fetchurl {
    name = "FW_RT-AC86U_300438652334.zip";
    url = "https://dlcdnets.asus.com/pub/ASUS/wireless/RT-AC86U/FW_RT-AC86U_300438652334.zip?model=RT-AC86U";
    hash = "sha256-6P0POibbT+nPastkJy0reCR+uczziQ+9uNqs4LrBDWE=";
  };
in
pkgs.runCommand "rt-ac86u-cferam-386-52334"
  {
    nativeBuildInputs = [
      pkgs.unzip
      pkgs.jefferson
    ];
    outputHashMode = "flat";
    outputHashAlgo = "sha256";
    outputHash = "sha256-ZCc2DT4Q1QfaEZXM/hyDQ/2MGHsGjh0QEfX1mUW8SxI=";
  }
  ''
    unzip -q ${firmware} RT-AC86U_3.0.0.4_386_52334-gd500e53_ubi.w
    head -c 3145728 RT-AC86U_3.0.0.4_386_52334-gd500e53_ubi.w > bootfs.jffs2
    jefferson bootfs.jffs2 -d bootfs > /dev/null
    cp bootfs/cferam.000 "$out"
  ''
