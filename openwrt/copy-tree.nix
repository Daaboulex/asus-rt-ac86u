{ pkgs }:
pkgs.writeShellApplication {
  name = "copy-tree";
  runtimeInputs = [ pkgs.rsync ];
  text = ''
    exec rsync -a --checksum --no-owner --no-group --delete --chmod=u+w "$@"
  '';
  meta = {
    description = "Mirror a tree by content, since every file in the Nix store carries the same time";
    mainProgram = "copy-tree";
  };
}
