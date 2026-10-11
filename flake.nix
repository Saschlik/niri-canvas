{
  description = "Niri Canvas — Interactive visual multi-monitor display manager for Niri Wayland compositor";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        niri-canvas = pkgs.callPackage ./default.nix { };
      in
      {
        packages = {
          default = niri-canvas;
          niri-canvas = niri-canvas;
        };

        apps = {
          default = flake-utils.lib.mkApp {
            drv = niri-canvas;
            name = "niri-canvas";
          };
          cli = flake-utils.lib.mkApp {
            drv = niri-canvas;
            name = "niri-canvas-cli";
          };
        };

        devShells.default = pkgs.mkShell {
          nativeBuildInputs = with pkgs; [
            wrapGAppsHook4
            gobject-introspection
          ];
          buildInputs = with pkgs; [
            gtk4
            libadwaita
            librsvg
            (python3.withPackages (ps: with ps; [
              pygobject3
            ]))
          ];
        };
      }
    );
}
