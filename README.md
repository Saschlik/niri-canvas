<div align="center">

<img src="assets/com.github.saschlik.NiriCanvas.svg" width="128" height="128" alt="Niri Canvas Icon" />

# Niri Canvas

### The visual multi-monitor display manager for the [Niri](https://github.com/YaLTeR/niri) Wayland compositor.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Nix Flake](https://img.shields.io/badge/Nix_Flake-ready-5277C3.svg?logo=nixos&logoColor=white)](flake.nix)
[![GTK4 & Libadwaita](https://img.shields.io/badge/UI-GTK4%20%26%20Libadwaita-40a02b.svg?logo=gnome&logoColor=white)](#requirements)
[![Wayland](https://img.shields.io/badge/Compositor-Niri%20Wayland-f5a97f.svg)](#)

</div>

---

**Niri Canvas** brings an intuitive, modern GNOME / macOS style multi-monitor arrangement experience to the **Niri** scrollable-tiling Wayland compositor.

No more manually calculating coordinates in `config.kdl` or wrestling with broken temporary `wlr-randr` workarounds. **Niri Canvas** visually previews your hardware, snaps screens together magnetistically, writes clean declarative KDL, and applies your layout instantly with zero compositor flicker.

---

## ✨ Features

* 🖥️ **Interactive 2D Hardware Canvas**  
  Monitors are rendered as realistic displays with stands, outer bezels, glossy screens, and circled display numbers ($1, 2, 3\dots$).
* 🧲 **Magnetic Edge-Snapping**  
  Displays snap seamlessly to each other's edges within a 75-pixel threshold, illuminated by neon-cyan alignment guidelines. No accidental dead zones, gaps, or mouse trapping.
* 🪄 **One-Click Auto-Align**  
  Automatically packs all connected displays side-by-side from left to right with zero gaps.
* 💡 **Display Identification**  
  Flashes on-screen overlay notifications on every connected display showing its assigned number, port, model, and active resolution.
* ⚙️ **Per-Monitor Inspector**  
  * **Resolution & Refresh Rate**: Select from native hardware modes with human-friendly labels (e.g. `1920×1080 @ 144Hz`).
  * **Orientation & Transform**: Rotate displays ($0^\circ$, $90^\circ$, $180^\circ$, $270^\circ$) with instant live aspect-ratio updates on the canvas.
  * **Scaling**: Adjust fractional scaling ($100\%$, $125\%$, $150\%$, $175\%$, $200\%$).
  * **Primary Display**: Toggle primary monitor flag with a single click.
  * **Pixel-Perfect Fine Tuning**: Manual $X$ and $Y$ coordinate inputs for exact positioning.
* ⚡ **Declarative Niri Engine**  
  Directly reads compositor state via `niri msg -j outputs`, formats clean KDL blocks, creates automatic `.bak` backups, and performs live reload via `niri msg action load-config-file`.
* 💻 **Headless CLI Included**  
  Run `niri-canvas status`, `niri-canvas align`, or `niri-canvas identify` directly from your shell or scripts.

---

## 🚀 Quick Start

### Try Instantly with Nix

```bash
# Launch GUI directly
nix run github:saschlik/niri-canvas

# Or inspect displays in terminal:
nix run github:saschlik/niri-canvas -- status
```

---

## 📦 Installation

### NixOS (Flake)

Add `niri-canvas` to your `flake.nix`:

```nix
{
  inputs = {
    niri-canvas.url = "github:saschlik/niri-canvas";
  };

  outputs = { self, nixpkgs, niri-canvas, ... }: {
    nixosConfigurations.my-host = nixpkgs.lib.nixosSystem {
      modules = [
        ({ pkgs, ... }: {
          environment.systemPackages = [
            niri-canvas.packages.${pkgs.system}.default
          ];
        })
      ];
    };
  };
}
```

### Arch Linux / Fedora / Ubuntu (Manual Install)

**1. Install dependencies:**

* **Arch Linux:**
  ```bash
  sudo pacman -S gtk4 libadwaita python-gobject
  ```
* **Fedora:**
  ```bash
  sudo dnf install gtk4 libadwaita python3-gobject
  ```
* **Ubuntu / Debian:**
  ```bash
  sudo apt install libgtk-4-dev libadwaita-1-dev python3-gi
  ```

**2. Clone and install:**

```bash
git clone https://github.com/saschlik/niri-canvas.git
cd niri-canvas
sudo make install
```

---

## ⌨️ Niri Integration

Bind **Niri Canvas** to a shortcut in your `~/.config/niri/config.kdl`:

```kdl
binds {
    Mod+Shift+D { spawn "niri-canvas"; }
}
```

---

## 🖥️ CLI Commands

```bash
# Print formatted display table
niri-canvas status

# Automatically align displays left-to-right
niri-canvas align

# Flash identification popups on all monitors
niri-canvas identify

# Custom KDL target path
niri-canvas -c ~/.config/niri/my-monitors.kdl
```

**Example CLI Output:**

```
===============================================================================================
 NIRI CANVAS — Connected Displays (4)
 Config Target: ~/.config/niri/source/monitors.kdl
===============================================================================================
PORT       PRIMARY  MODEL                RESOLUTION             SCALE    ROT      POSITION (X,Y) 
-----------------------------------------------------------------------------------------------
DP-1       ★ JA     DELL U2412M          1920×1200 @ 60Hz       100%     270      0, 0           
DVI-D-1    NEIN     DELL U2412M          1920×1200 @ 60Hz       100%     90       1200, 0        
HDMI-A-1   NEIN     27G1G4               1920×1080 @ 144Hz      100%     Normal   2400, 420      
DP-2       NEIN     DELL U2412M          1920×1200 @ 60Hz       100%     Normal   4320, 360      
===============================================================================================
```

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
Designed for the [Niri](https://github.com/YaLTeR/niri) Wayland community.
