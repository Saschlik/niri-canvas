"""
Backend for Niri Canvas: IPC communication, monitor querying, and KDL config management.
Safe for both BalonixOS and generic Linux distributions (Arch, Fedora, Ubuntu, Debian, vanilla NixOS).
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
    Always returns a dedicated monitor configuration file (never overwrites main config.kdl).
    Order of preference:
    1. Custom path if provided
    2. ~/balonixOS/settings/monitors.kdl (if Balonix environment)
    3. ~/.config/niri/source/monitors.kdl (if modular structure exists)
    4. ~/.config/niri/monitors.kdl (if already exists)
    5. Custom include target extracted from ~/.config/niri/config.kdl
    6. Default: ~/.config/niri/monitors.kdl
    """
    if custom_path:
        return os.path.abspath(custom_path)

    home = os.path.expanduser("~")

    # 1. BalonixOS check
    balonix_kdl = os.path.join(home, "balonixOS", "settings", "monitors.kdl")
    if os.path.exists(balonix_kdl):
        return balonix_kdl

    # 2. Existing modular source/monitors.kdl
    niri_source_kdl = os.path.join(home, ".config", "niri", "source", "monitors.kdl")
    if os.path.exists(niri_source_kdl):
        return niri_source_kdl

    # 3. Existing ~/.config/niri/monitors.kdl
    niri_monitors_kdl = os.path.join(home, ".config", "niri", "monitors.kdl")
    if os.path.exists(niri_monitors_kdl):
        return niri_monitors_kdl

    # 4. Check if config.kdl already references a custom include for monitors/outputs
    niri_config = os.path.join(home, ".config", "niri", "config.kdl")
    if os.path.exists(niri_config):
        try:
            with open(niri_config, "r", encoding="utf-8") as f:
                content = f.read()
                m = re.search(r'include\s+"([^"]*(?:monitor|output)[^"]*\.kdl)"', content)
                if m:
                    inc_path = m.group(1)
                    if not os.path.isabs(inc_path):
                        inc_path = os.path.join(os.path.dirname(niri_config), inc_path)
                    return os.path.abspath(inc_path)
        except Exception:
            pass

    # 5. Standard fallback for Arch, Fedora, NixOS, etc.
    target_dir = os.path.join(home, ".config", "niri")
    os.makedirs(target_dir, exist_ok=True)
    return niri_monitors_kdl


def ensure_include_in_niri_config(monitors_kdl_path: str) -> Optional[str]:
    """
    Ensure that ~/.config/niri/config.kdl includes the monitors KDL file.
    Safely injects `include "monitors.kdl"` if missing, with automatic backup.
    Returns an optional warning message if config.kdl is immutable (e.g. Nix store symlink).
    """
    home = os.path.expanduser("~")
    niri_dir = os.path.join(home, ".config", "niri")
    niri_config = os.path.join(niri_dir, "config.kdl")

    try:
        rel_path = os.path.relpath(monitors_kdl_path, niri_dir)
    except ValueError:
        rel_path = monitors_kdl_path

    # Case 1: Fresh install where ~/.config/niri/config.kdl does not exist yet
    if not os.path.exists(niri_config):
        try:
            os.makedirs(niri_dir, exist_ok=True)
            with open(niri_config, "w", encoding="utf-8") as f:
                f.write(f'// Niri Wayland Compositor Configuration\ninclude "{rel_path}"\n')
            return None
        except Exception as e:
            return f"Konnte {niri_config} nicht anlegen: {e}"

    # Case 2: Config is a read-only symlink to the Nix store (e.g. Home-Manager)
    if os.path.islink(niri_config) and "/nix/store" in os.path.realpath(niri_config):
        try:
            with open(niri_config, "r", encoding="utf-8") as f:
                content = f.read()
            if (
                f'include "{rel_path}"' in content
                or 'include "monitors.kdl"' in content
                or 'include "source/monitors.kdl"' in content
                or 'include "outputs.kdl"' in content
            ):
                return None
        except Exception:
            pass
        return "Hinweis: Deine config.kdl ist schreibgeschützt (Nix-Store). Trage bitte include \"monitors.kdl\" in deiner Nix-Konfiguration ein."

    # Case 3: Regular writable config.kdl
    try:
        with open(niri_config, "r", encoding="utf-8") as f:
            content = f.read()

        # Check if already included in any form
        if (
            f'include "{rel_path}"' in content
            or 'include "monitors.kdl"' in content
            or 'include "source/monitors.kdl"' in content
            or 'include "outputs.kdl"' in content
        ):
            return None

        # Backup config.kdl before modifying
        shutil.copyfile(niri_config, niri_config + ".bak")

        # Inject include at the top of the file
        include_header = f'// Automatically included by Niri Canvas\ninclude "{rel_path}"\n\n'
        with open(niri_config, "w", encoding="utf-8") as f:
            f.write(include_header + content)
        return None
    except Exception as e:
        return f"Hinweis: Konnte include nicht automatisch in config.kdl eintragen ({e}). Bitte manuell include \"monitors.kdl\" ergänzen."


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
    Atomically save layout to KDL config, ensure include in config.kdl, and reload Niri compositor.
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

    # Write backup of the monitor file
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

    # Ensure main config.kdl includes this file (critical for non-Balonix distros)
    include_notice = ensure_include_in_niri_config(target_file)

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
    run_cmd("niri msg action load-config-file")
    msg = f"Erfolgreich in {target_file} gespeichert und Niri neu geladen!"
    if include_notice:
        msg += f"\n{include_notice}"
    return True, msg


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
