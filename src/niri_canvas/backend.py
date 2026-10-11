"""
Backend for Niri Canvas: IPC communication, monitor querying, and KDL config management.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple, Any


def run_cmd(cmd: str) -> str:
    """Execute a shell command and return trimmed output."""
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.stdout.strip()
    except Exception:
        return ""


def find_config_file(custom_path: Optional[str] = None) -> str:
    """
    Resolve the path to the monitors KDL file.
    Order of preference:
    1. Custom path if provided
    2. ~/balonixOS/settings/monitors.kdl (if Balonix environment)
    3. ~/.config/niri/source/monitors.kdl (if modular structure)
    4. ~/.config/niri/monitors.kdl
    5. ~/.config/niri/config.kdl (standard Niri config)
    """
    if custom_path and os.path.exists(custom_path):
        return os.path.abspath(custom_path)

    home = os.path.expanduser("~")

    # BalonixOS check
    balonix_kdl = os.path.join(home, "balonixOS", "settings", "monitors.kdl")
    if os.path.exists(balonix_kdl):
        return balonix_kdl

    # Niri standard modular configs
    niri_source_kdl = os.path.join(home, ".config", "niri", "source", "monitors.kdl")
    if os.path.exists(niri_source_kdl):
        return niri_source_kdl

    niri_monitors_kdl = os.path.join(home, ".config", "niri", "monitors.kdl")
    if os.path.exists(niri_monitors_kdl):
        return niri_monitors_kdl

    niri_config = os.path.join(home, ".config", "niri", "config.kdl")
    if os.path.exists(niri_config):
        # Check if config.kdl includes monitors.kdl
        try:
            with open(niri_config, "r", encoding="utf-8") as f:
                content = f.read()
                if 'include "monitors.kdl"' in content:
                    return niri_monitors_kdl
                if 'include "source/monitors.kdl"' in content:
                    return niri_source_kdl
        except Exception:
            pass
        return niri_config

    # Default fallback
    target_dir = os.path.join(home, ".config", "niri")
    os.makedirs(target_dir, exist_ok=True)
    return niri_monitors_kdl


def get_monitors() -> List[Dict[str, Any]]:
    """
    Query Niri compositor for all connected monitors via `niri msg -j outputs`.
    Returns normalized monitor dicts.
    """
    raw = run_cmd("niri msg -j outputs 2>/dev/null")
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    monitors: List[Dict[str, Any]] = []

    for port, info in data.items():
        cur_mode_idx = info.get("current_mode", 0)
        raw_modes = info.get("modes", [])

        mode_list = []
        seen_modes = set()
        for m in raw_modes:
            w = m.get("width", 0)
            h = m.get("height", 0)
            rr = m.get("refresh_rate", 0)
            hz = round(rr / 1000)
            mode_key = f"{w}x{h}@{rr/1000:.3f}"
            label = f"{w}×{h} @ {hz}Hz"
            if mode_key not in seen_modes:
                seen_modes.add(mode_key)
                mode_list.append({
                    "width": w,
                    "height": h,
                    "refresh_rate": rr,
                    "hz": hz,
                    "mode_str": mode_key,
                    "label": label,
                    "is_preferred": m.get("is_preferred", False)
                })

        # Sort modes: resolution descending, refresh rate descending
        mode_list.sort(key=lambda x: (x["width"] * x["height"], x["hz"]), reverse=True)

        cur_mode_str = "--"
        cur_mode_label = "--"
        phys_w = 1920
        phys_h = 1080
        if isinstance(cur_mode_idx, int) and 0 <= cur_mode_idx < len(raw_modes):
            cm = raw_modes[cur_mode_idx]
            phys_w = cm.get("width", 1920)
            phys_h = cm.get("height", 1080)
            rr = cm.get("refresh_rate", 0)
            hz = round(rr / 1000)
            cur_mode_str = f"{phys_w}x{phys_h}@{rr/1000:.3f}"
            cur_mode_label = f"{phys_w}×{phys_h} @ {hz}Hz"
        elif mode_list:
            phys_w = mode_list[0]["width"]
            phys_h = mode_list[0]["height"]
            cur_mode_str = mode_list[0]["mode_str"]
            cur_mode_label = mode_list[0]["label"]

        logical = info.get("logical", {}) or {}
        tf = str(logical.get("transform", "Normal"))
        scale_val = float(logical.get("scale", 1.0) or 1.0)

        # Calculate logical dimensions
        log_w = logical.get("width")
        log_h = logical.get("height")
        if not log_w or not log_h:
            if tf in ["90", "270"]:
                log_w = int(round(phys_h / scale_val))
                log_h = int(round(phys_w / scale_val))
            else:
                log_w = int(round(phys_w / scale_val))
                log_h = int(round(phys_h / scale_val))

        tf_disp = "Normal (0°)"
        if tf == "90":
            tf_disp = "90° (Rechts)"
        elif tf == "180":
            tf_disp = "180° (Überkopf)"
        elif tf == "270":
            tf_disp = "270° (Links)"

        monitors.append({
            "port": port,
            "name": info.get("name", port),
            "model": info.get("model", port),
            "make": info.get("make", ""),
            "serial": info.get("serial", ""),
            "mode": cur_mode_str,
            "mode_label": cur_mode_label,
            "modes": mode_list,
            "scale": scale_val,
            "transform": tf,
            "transform_display": tf_disp,
            "x": int(logical.get("x", 0)),
            "y": int(logical.get("y", 0)),
            "width": int(log_w),
            "height": int(log_h),
            "phys_width": int(phys_w),
            "phys_height": int(phys_h),
            "is_primary": False
        })

    # Sort left to right
    monitors.sort(key=lambda m: (m.get("x", 0), m.get("y", 0), m.get("port", "")))
    if monitors:
        # Default primary to the first display or one matching config
        monitors[0]["is_primary"] = True

    return monitors


def auto_align_monitors(monitors_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Arrange monitors side-by-side from left to right with 0 gaps or dead zones.
    """
    sorted_monitors = sorted(monitors_data, key=lambda m: (m.get("x", 0), m.get("port", "")))
    cur_x = 0
    aligned = []
    for m in sorted_monitors:
        item = dict(m)
        item["x"] = cur_x
        item["y"] = 0
        cur_x += item.get("width", 1920)
        aligned.append(item)
    return aligned


def save_monitors_layout(monitors_data: List[Dict[str, Any]], custom_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Atomically save layout to KDL config and reload Niri compositor.
    Returns (success, message).
    """
    if not monitors_data:
        return False, "Keine Monitore zum Speichern vorhanden."

    target_file = find_config_file(custom_path)
    os.makedirs(os.path.dirname(target_file), exist_ok=True)

    # Normalize coordinates so min_x = 0, min_y = 0
    min_x = min(m.get("x", 0) for m in monitors_data)
    min_y = min(m.get("y", 0) for m in monitors_data)

    normalized = []
    for m in monitors_data:
        item = dict(m)
        item["x"] = max(0, int(round(m.get("x", 0) - min_x)))
        item["y"] = max(0, int(round(m.get("y", 0) - min_y)))
        normalized.append(item)

    normalized.sort(key=lambda m: (m.get("x", 0), m.get("y", 0), m.get("port", "")))

    # Generate KDL output
    lines = [
        "// Niri Canvas — Monitor Configuration",
        "// Automatically generated by Niri Canvas visual manager",
        "// Format: https://yalter.github.io/niri/Configuration:-Outputs",
        ""
    ]

    for m in normalized:
        port = m.get("port", "")
        if not port:
            continue
        lines.append(f'output "{port}" {{')
        mode = m.get("mode")
        if mode and mode != "--":
            lines.append(f'    mode "{mode}"')
        tf = str(m.get("transform", "Normal")).strip()
        if tf.lower() not in ["normal", "0", ""]:
            lines.append(f'    transform "{tf}"')
        scale = m.get("scale", 1.0)
        try:
            scale_f = float(scale)
            if abs(scale_f - 1.0) > 0.001:
                lines.append(f'    scale {scale_f}')
        except Exception:
            pass
        x = m.get("x", 0)
        y = m.get("y", 0)
        lines.append(f'    position x={x} y={y}')
        lines.append('}\n')

    kdl_content = "\n".join(lines)

    # Write backup
    if os.path.exists(target_file):
        try:
            shutil.copyfile(target_file, target_file + ".bak")
        except Exception:
            pass

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(kdl_content)
    except Exception as e:
        return False, f"Fehler beim Schreiben von {target_file}: {e}"

    # BalonixOS integration: also update settings/monitors.nix if present
    home = os.path.expanduser("~")
    nix_file = os.path.join(home, "balonixOS", "settings", "monitors.nix")
    if os.path.exists(os.path.dirname(nix_file)):
        nix_lines = [
            "# BalonixOS Deklarative Monitor-Konfiguration",
            "# Generiert durch Niri Canvas",
            "{ config, lib, ... }:",
            "",
            "{",
            "  balonix.displays = ["
        ]
        for m in normalized:
            p = m.get("port", "")
            mod = m.get("model", p)
            md = m.get("mode", "")
            tf = str(m.get("transform", "Normal"))
            sc = m.get("scale", 1.0)
            x = m.get("x", 0)
            y = m.get("y", 0)
            is_prim = "true" if m.get("is_primary") else "false"
            nix_lines.append("    {")
            nix_lines.append(f'      port = "{p}";')
            nix_lines.append(f'      model = "{mod}";')
            if md and md != "--":
                nix_lines.append(f'      mode = "{md}";')
            nix_lines.append(f'      transform = "{tf}";')
            nix_lines.append(f'      scale = {sc};')
            nix_lines.append(f'      x = {x};')
            nix_lines.append(f'      y = {y};')
            nix_lines.append(f'      primary = {is_prim};')
            nix_lines.append("    }")
        nix_lines.append("  ];")
        nix_lines.append("}")
        try:
            with open(nix_file, "w", encoding="utf-8") as f:
                f.write("\n".join(nix_lines) + "\n")
        except Exception:
            pass

    # Hot reload Niri
    reload_res = run_cmd("niri msg action load-config-file")
    return True, f"Erfolgreich gespeichert in {target_file} und in Niri angewendet!"


def identify_monitors(monitors_data: Optional[List[Dict[str, Any]]] = None):
    """
    Send high-priority notifications to identify each monitor with its index, port, and resolution.
    """
    if monitors_data is None:
        monitors_data = get_monitors()

    for idx, m in enumerate(monitors_data, 1):
        port = m.get("port", "")
        model = m.get("model", port)
        w = m.get("width", 0)
        h = m.get("height", 0)
        tf = m.get("transform_display", "Normal")
        hz = m.get("mode_label", "")
        prim = " ★ [HAUPT]" if m.get("is_primary") else ""
        run_cmd(
            f"notify-send -a 'Niri Canvas' -i 'video-display-symbolic' -t 5000 "
            f"'Display {idx}: {port}{prim}' '{model}\n{w}×{h} • {hz} • {tf}'"
        )
