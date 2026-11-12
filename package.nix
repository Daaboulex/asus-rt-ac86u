{
  lib,
  buildPythonApplication,
  setuptools,
  pytestCheckHook,
}:
buildPythonApplication {
  pname = "asus-rescue";
  version =
    let
      parts = lib.splitString ''__version__ = "'' (builtins.readFile ./src/asus_rescue/__init__.py);
    in
    assert lib.assertMsg (
      builtins.length parts == 2
    ) "package.nix: expected exactly one __version__ assignment in src/asus_rescue/__init__.py";
    lib.head (lib.splitString ''"'' (lib.last parts));
  pyproject = true;

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./pyproject.toml
      ./src
      ./tests
    ];
  };

  build-system = [ setuptools ];

  nativeCheckInputs = [ pytestCheckHook ];

  pythonImportsCheck = [ "asus_rescue" ];

  meta = {
    description = "Flash an image to an ASUS router in rescue mode over its LAN port";
    license = lib.licenses.mit;
    mainProgram = "asus-rescue";
    platforms = lib.platforms.linux;
  };
}
