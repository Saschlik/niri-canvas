"""
Application Entrypoint for Niri Canvas.
Supports both GUI (Libadwaita) and Headless CLI modes.
"""
import argparse
import os
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

from .ui import NiriCanvasWindow
from .backend import (
    get_monitors,
    save_monitors_layout,
    auto_align_monitors,
    identify_monitors,
    find_config_file,
)

VERSION = "1.0.0"


def run_cli_status():
    monitors = get_monitors()
    if not monitors:
        print("Keine aktiven Monitore in Niri gefunden.")
        return 1

    print("\n" + "=" * 95)
    print(f" NIRI CANVAS — Connected Displays ({len(monitors)})")
    print(f" Config Target: {find_config_file()}")
    print("=" * 95)
    header = f"{'PORT':<10} {'PRIMARY':<8} {'MODEL':<20} {'RESOLUTION':<22} {'SCALE':<8} {'ROT':<8} {'POSITION (X,Y)':<15}"
    print(header)
    print("-" * 95)
    for m in monitors:
        prim = "★ JA" if m.get("is_primary") else "NEIN"
        port = m.get("port", "")
        model = m.get("model", "")[:18]
        mode = m.get("mode_label", m.get("mode", ""))[:20]
        scale = f"{int(round(float(m.get('scale', 1.0)) * 100))}%"
        rot = str(m.get("transform", "Normal"))
        pos = f"{m.get('x', 0)}, {m.get('y', 0)}"
        print(f"{port:<10} {prim:<8} {model:<20} {mode:<22} {scale:<8} {rot:<8} {pos:<15}")
    print("=" * 95 + "\n")
    return 0


def run_cli_align(config_path=None):
    monitors = get_monitors()
    if not monitors:
        print("Keine Monitore zum Anordnen gefunden.")
        return 1
    aligned = auto_align_monitors(monitors)
    success, msg = save_monitors_layout(aligned, config_path)
    print(msg)
    return 0 if success else 1


def run_cli_identify():
    identify_monitors()
    print("Identifizierungs-Meldungen an alle Displays gesendet.")
    return 0


class NiriCanvasApp(Adw.Application):
    def __init__(self, custom_config=None):
        super().__init__(
            application_id="com.github.saschlik.NiriCanvas",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.custom_config = custom_config

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = NiriCanvasWindow(self, custom_config=self.custom_config)
        win.present()


def main():
    parser = argparse.ArgumentParser(
        prog="niri-canvas",
        description="Niri Canvas — Visual Multi-Monitor Manager for Niri Wayland Compositor"
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("-c", "--config", type=str, help="Pfad zu einer benutzerdefinierten KDL-Konfigurationsdatei")

    subparsers = parser.add_subparsers(dest="command", help="Optionale CLI-Befehle")

    subparsers.add_parser("status", help="Zeigt aktuelle Monitore und Koordinaten in der Konsole an")
    subparsers.add_parser("align", help="Richtet alle Monitore automatisch lückenlos nebeneinander aus")
    subparsers.add_parser("identify", help="Sendet visuelle Identifikations-Overlays an alle Bildschirme")

    args, unknown = parser.parse_known_args()

    if args.command == "status":
        sys.exit(run_cli_status())
    elif args.command == "align":
        sys.exit(run_cli_align(args.config))
    elif args.command == "identify":
        sys.exit(run_cli_identify())

    # Default to GUI mode
    app = NiriCanvasApp(custom_config=args.config)
    sys.exit(app.run([sys.argv[0]] + unknown))


if __name__ == "__main__":
    main()
