# AGENTS.md

Instructions for AI assistants. CONTRIBUTING.md applies to you as well; read it first.

@CONTRIBUTING.md

- Working for someone, show a change before making it. "Show me first" means show it and stop.
- Say a change's effect as what someone will see break, and whether git, access or data is touched.
- When a decision is someone else's, give options and name the one you recommend. Act only on the
  options chosen; a remark is a condition, and an unclear one is asked, never guessed.
- Before fixing a failure, say what kind it is: your own mistake, the environment, an upstream
  break, or a real defect. Then fix what let it through as well.
- When you notice a gap, such as something someone would get wrong, a missing check or a doc that no
  longer matches the code, say so and propose the fix: in this project's part below, or as an issue
  in `Daaboulex/nix-packaging-standard` when it concerns every repo.
- Keep this file short and written by people. Add a rule only when someone got something wrong that
  no check catches.

## This project

- A green `nix flake check` proves the series applies and the checks hold, not that the router
  works. A change to the image is run on the unit with `nix run .#hardware-test` before it lands.
- Before a test that can cut access to the unit, know the way back: failsafe or rescue mode, as
  the README describes.
- Resetting or reflashing the router cuts every host whose route goes through it. Say when a
  series of resets starts and ends, so nothing else fetches through the router meanwhile.
- Never unload `brcmfmac` on a running unit: its teardown can oops, on 10.28.2 and on newer radio
  firmware alike. Reboot instead.
- Bring Wi-Fi back with `wifi down` then `wifi up`. A partial reload has reordered the access
  points' MAC addresses before.
- Read the crash records in `/sys/fs/pstore` after a test and copy them off before deleting them:
  `misc3` holds only 16, and a full store drops the next panic.
- Edit an inner patch by regenerating it from the file before and after it, never by adjusting
  hunk counts by hand. A hunk that applies with an offset or fuzz has a stale header: fix it, the
  series check accepts both.
- A measurement quoted in the docs says when and how it was taken, as the existing ones do.
