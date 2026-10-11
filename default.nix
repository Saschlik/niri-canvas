{ lib
, stdenv
, python3
, gtk4
, libadwaita
, wrapGAppsHook4
, gobject-introspection
, librsvg
}:

let
  pythonEnv = python3.withPackages (ps: with ps; [
    pygobject3
  ]);
in
stdenv.mkDerivation {
  pname = "niri-canvas";
  version = "1.0.0";

  src = ./.;

  nativeBuildInputs = [
    wrapGAppsHook4
    gobject-introspection
  ];

  buildInputs = [
    pythonEnv
    gtk4
    libadwaita
    librsvg
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/niri-canvas
    cp -r src/niri_canvas $out/lib/niri-canvas/

    mkdir -p $out/bin
    cat << PYEOF > $out/bin/niri-canvas
#!${pythonEnv}/bin/python3
import sys
import os
sys.path.insert(0, "$out/lib/niri-canvas")
from niri_canvas.main import main
if __name__ == "__main__":
    sys.exit(main())
PYEOF
    chmod +x $out/bin/niri-canvas
    ln -sf niri-canvas $out/bin/niri-canvas-cli

    mkdir -p $out/share/applications
    install -Dm644 ui/com.github.saschlik.NiriCanvas.desktop $out/share/applications/

    mkdir -p $out/share/icons/hicolor/scalable/apps
    install -Dm644 assets/com.github.saschlik.NiriCanvas.svg $out/share/icons/hicolor/scalable/apps/

    mkdir -p $out/share/icons/hicolor/256x256/apps
    install -Dm644 assets/com.github.saschlik.NiriCanvas.png $out/share/icons/hicolor/256x256/apps/

    runHook postInstall
  '';

  meta = with lib; {
    description = "Interactive visual multi-monitor display manager for Niri Wayland compositor";
    homepage = "https://github.com/saschlik/niri-canvas";
    license = licenses.mit;
    platforms = platforms.linux;
    mainProgram = "niri-canvas";
  };
}
