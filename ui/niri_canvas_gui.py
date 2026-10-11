#!/usr/bin/env python3
"""
Niri Canvas — Standalone GNOME / Libadwaita App Launcher
Equivalent to ClickClick's ui/clickclick_gui.py.
"""
import os
import sys

# Set up paths so it can be run directly from anywhere: python3 ui/niri_canvas_gui.py
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.abspath(os.path.join(script_dir, ".."))
bin_launcher = os.path.join(repo_dir, "bin", "niri-canvas")

if os.path.exists(bin_launcher):
    os.execv(sys.executable, [sys.executable, bin_launcher] + sys.argv[1:])
else:
    src_dir = os.path.join(repo_dir, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from niri_canvas.main import main
    main()
