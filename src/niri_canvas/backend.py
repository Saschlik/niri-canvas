"""
Backend for Niri Canvas: IPC communication, monitor querying, and KDL config management.
Safe for both BalonixOS and generic Linux distributions (Arch, Fedora, Ubuntu, Debian, vanilla NixOS).
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple, Union, Any


NIRI_TRANSFORM_MAP = {
    "normal": "normal",
    "0": "normal",
    "90": "90",
    "180": "180",
    "270": "270",
    "flipped": "flipped",
    "flipped90": "flipped-90",
    "flipped-90": "flipped-90",
    "flipped180": "flipped-180",
    "flipped-180": "flipped-180",
    "flipped270": "flipped-270",
    "flipped-270": "flipped-270",
}


def normalize_kdl_transform(tf: str) -> str:
    """Normalize a Niri IPC transform string to valid Niri KDL syntax."""
    key = str(tf or "Normal").strip().lower()
    return NIRI_TRANSFORM_MAP.get(key, "normal")


def is_rotated_90_or_270(tf: str) -> bool:
    """Return True if transform rotates aspect ratio by 90 or 270 degrees."""
    return normalize_kdl_transform(tf) in ("90", "270", "flipped-90", "flipped-270")


def run_cmd(cmd: Union[List[str], str]) -> str:
    """Execute a command safely without shell=True and return trimmed stdout."""
    try:
        args = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        res = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def find_config_file(custom_path: Optional[str] = None) -> str:
    """
    Resolve the path to the monitors KDL file.
    Always returns a dedicated monitor configuration file (never overwrites main config.kdl).
    Order of preference:
    1. Custom path if provided
    2. ~/.config/niri/source/monitors.kdl (resolved via realpath if symlink)
    3. ~/.config/niri/monitors.kdl (if already exists)
    4. Custom include target extracted from ~/.config/niri/config.kdl
    5. ~/balonixOS/settings/monitors.kdl (if Balonix environment)
    6. Default: ~/.config/niri/monitors.kdl
    """
    if custom_path:
        return os.path.abspath(custom_path)

    home = os.path.expanduser("~")

    # 1. Existing modular ~/.config/niri/source/monitors.kdl (follow symlink if present)
    niri_source_kdl = os.path.join(home, ".config", "niri", "source", "monitors.kdl")
    if os.path.exists(niri_source_kdl):
        resolved = os.path.realpath(niri_source_kdl)
        if not resolved.startswith("/nix/store"):
            return resolved

    # 2. Existing ~/.config/niri/monitors.kdl
    niri_monitors_kdl = os.path.join(home, ".config", "niri", "monitors.kdl")
    if os.path.exists(niri_monitors_kdl):
        return os.path.realpath(niri_monitors_kdl)

    # 3. Check if config.kdl already references a custom include for monitors/outputs
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
                    resolved = os.path.realpath(inc_path)
                    if os.path.exists(resolved) and not resolved.startswith("/nix/store"):
                        return resolved
        except Exception:
            pass

    # 4. BalonixOS fallback
    balonix_kdl = os.path.join(home, "balonixOS", "settings", "monitors.kdl")
    if os.path.exists(balonix_kdl):
        return balonix_kdl

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
            return f"Could not create {niri_config}: {e}"

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
        return 'Notice: Your config.kdl is read-only (Nix store). Please add include "monitors.kdl" to your Nix configuration.'

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

        # Backup config.kdl to ~/.cache/niri-canvas before modifying
        cache_dir = os.path.join(home, ".cache", "niri-canvas")
        os.makedirs(cache_dir, exist_ok=True)
        shutil.copyfile(niri_config, os.path.join(cache_dir, "config.kdl.bak"))

        # Inject include at the top of the file
        include_header = f'// Automatically included by Niri Canvas\ninclude "{rel_path}"\n\n'
        with open(niri_config, "w", encoding="utf-8") as f:
            f.write(include_header + content)
        return None
    except Exception as e:
        return f'Notice: Could not automatically inject include into config.kdl ({e}). Please manually add include "monitors.kdl".'


def get_monitors() -> List[Dict[str, Any]]:
    """
    Query Niri compositor for all connected monitors via `niri msg -j outputs`.
    Returns normalized monitor dicts.
    """
    raw = run_cmd(["niri", "msg", "-j", "outputs"])
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
            if is_rotated_90_or_270(tf):
                log_w = int(round(phys_h / scale_val))
                log_h = int(round(phys_w / scale_val))
            else:
                log_w = int(round(phys_w / scale_val))
                log_h = int(round(phys_h / scale_val))

        tf_norm = normalize_kdl_transform(tf)
        tf_labels = {
            "normal": "Normal (0°)",
            "90": "90° (Right)",
            "180": "180° (Inverted)",
            "270": "270° (Left)",
            "flipped": "Flipped (0°)",
            "flipped-90": "Flipped 90°",
            "flipped-180": "Flipped 180°",
            "flipped-270": "Flipped 270°",
        }
        tf_disp = tf_labels.get(tf_norm, "Normal (0°)")

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
        return False, "No monitors to save."

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
        tf_kdl = normalize_kdl_transform(str(m.get("transform", "Normal")))
        if tf_kdl != "normal":
            lines.append(f'    transform "{tf_kdl}"')
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

    # Store backup in ~/.cache/niri-canvas/ so we never pollute git repositories
    if os.path.exists(target_file):
        try:
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "niri-canvas")
            os.makedirs(cache_dir, exist_ok=True)
            shutil.copyfile(target_file, os.path.join(cache_dir, "monitors.kdl.bak"))
        except Exception:
            pass

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(kdl_content)
    except Exception as e:
        return False, f"Failed to write {target_file}: {e}"

    # Ensure main config.kdl includes this file (critical for non-Balonix distros)
    include_notice = ensure_include_in_niri_config(target_file)

    # Hot reload Niri
    run_cmd(["niri", "msg", "action", "load-config-file"])
    msg = f"Successfully saved to {target_file} and reloaded Niri!"
    if include_notice:
        msg += f"\n{include_notice}"
    return True, msg


def identify_monitors(monitors_data: Optional[List[Dict[str, Any]]] = None):
    """
    Send high-priority notifications to identify each monitor with its index, port, and resolution.
    Uses safe argument lists (no shell interpolation).
    """
    if monitors_data is None:
        monitors_data = get_monitors()

    if not shutil.which("notify-send"):
        return

    for idx, m in enumerate(monitors_data, 1):
        port = str(m.get("port", ""))
        model = str(m.get("model", port))
        w = m.get("width", 0)
        h = m.get("height", 0)
        tf = str(m.get("transform_display", "Normal"))
        hz = str(m.get("mode_label", ""))
        prim = " ★ [PRIMARY]" if m.get("is_primary") else ""
        try:
            subprocess.Popen(
                [
                    "notify-send",
                    "-a",
                    "Niri Canvas",
                    "-i",
                    "video-display-symbolic",
                    "-t",
                    "5000",
                    f"Display {idx}: {port}{prim}",
                    f"{model}\n{w}×{h} • {hz} • {tf}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def _get_gio_settings():
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # type: ignore
        return Gio.Settings.new("org.gnome.desktop.interface")
    except Exception:
        return None


def get_font_rendering_settings() -> Dict[str, str]:
    """
    Retrieve current desktop font rendering and subpixel anti-aliasing settings.
    Returns:
        {
            "subpixel": "grayscale" | "rgb" | "bgr" | "vrgb" | "vbgr",
            "hinting": "none" | "slight" | "medium" | "full"
        }
    """
    result = {"subpixel": "rgb", "hinting": "slight"}
    s = _get_gio_settings()
    if s:
        try:
            aa = s.get_string("font-antialiasing")
            rgba = s.get_string("font-rgba-order")
            hinting = s.get_string("font-hinting")

            if aa in ["grayscale", "none"] or rgba == "none":
                result["subpixel"] = "grayscale"
            elif rgba in ["rgb", "bgr", "vrgb", "vbgr"]:
                result["subpixel"] = rgba
            else:
                result["subpixel"] = "rgb"

            if hinting in ["none", "slight", "medium", "full"]:
                result["hinting"] = hinting
            else:
                result["hinting"] = "slight"
        except Exception:
            pass
    return result


def set_font_rendering_settings(subpixel: str, hinting: str) -> Tuple[bool, str]:
    """
    Apply desktop font rendering and subpixel layout to GSettings and Fontconfig.
    Returns (success, message).
    """
    success = False
    details = []

    # 1. Update GSettings (affects GTK3/4, Libadwaita, Web Browsers, Qt via portal)
    s = _get_gio_settings()
    if s:
        try:
            if subpixel == "grayscale":
                s.set_string("font-antialiasing", "grayscale")
                s.set_string("font-rgba-order", "rgba")
            else:
                s.set_string("font-antialiasing", "rgba")
                s.set_string("font-rgba-order", subpixel)

            s.set_string("font-hinting", hinting)
            details.append("GSettings")
            success = True
        except Exception as e:
            print(f"Warning: Could not set Gio font settings: {e}", file=sys.stderr)

    # 2. Synchronize Fontconfig (~/.config/fontconfig/conf.d/10-subpixel.conf)
    try:
        home = os.path.expanduser("~")
        fc_dir = os.path.join(home, ".config", "fontconfig", "conf.d")
        os.makedirs(fc_dir, exist_ok=True)
        fc_file = os.path.join(fc_dir, "10-subpixel.conf")

        fc_rgba = "none" if subpixel == "grayscale" else subpixel
        fc_hintstyle = f"hint{hinting}" if hinting != "none" else "hintnone"
        fc_hinting_bool = "false" if hinting == "none" else "true"

        fc_xml = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<!-- Generated by Niri Canvas for Subpixel & Font Rendering -->
<fontconfig>
  <match target="font">
    <edit name="rgba" mode="assign">
      <const>{fc_rgba}</const>
    </edit>
    <edit name="antialias" mode="assign">
      <bool>true</bool>
    </edit>
    <edit name="hinting" mode="assign">
      <bool>{fc_hinting_bool}</bool>
    </edit>
    <edit name="hintstyle" mode="assign">
      <const>{fc_hintstyle}</const>
    </edit>
    <edit name="lcdfilter" mode="assign">
      <const>lcddefault</const>
    </edit>
  </match>
</fontconfig>
"""
        with open(fc_file, "w", encoding="utf-8") as f:
            f.write(fc_xml)
        if shutil.which("fc-cache"):
            subprocess.Popen(
                ["fc-cache", "-r"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        details.append("Fontconfig")
        success = True
    except Exception as e:
        print(f"Warning: Could not write fontconfig snippet: {e}", file=sys.stderr)

    if success:
        return True, f"Font rendering updated ({', '.join(details)} synchronized)."
    return False, "Failed to apply font rendering settings."
