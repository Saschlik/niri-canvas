"""
Libadwaita User Interface for Niri Canvas.
Provides a modern GNOME desktop experience with clear separation between
'Einfach' (Simple / Visual Layout) and 'Erweitert' (Advanced / Hardware & KDL).
"""
import json
import os
import sys
from typing import Dict, List, Optional, Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from .canvas import MonitorCanvas
from .backend import (
    get_monitors,
    save_monitors_layout,
    auto_align_monitors,
    identify_monitors,
    find_config_file,
    run_cmd
)


class NiriCanvasWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, custom_config: Optional[str] = None):
        super().__init__(application=app, title="Niri Canvas")
        self.custom_config = custom_config
        self.set_default_size(980, 760)
        self.set_size_request(600, 520)

        self.monitors: List[Dict[str, Any]] = []
        self._updating: bool = False

        # Toast Overlay
        self.toast_overlay = Adw.ToastOverlay.new()
        self.set_content(self.toast_overlay)

        # Main Box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.toast_overlay.set_child(main_box)

        # ── HeaderBar ─────────────────────────────────────────────────────────
        header = Adw.HeaderBar()

        # View Stack for Simple vs. Advanced
        self.view_stack = Adw.ViewStack()

        # ViewSwitcher in HeaderBar Title
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        # Left Header: Refresh
        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_btn.set_tooltip_text("Reload hardware & discard changes")
        self.refresh_btn.connect("clicked", self.on_refresh_clicked)
        header.pack_start(self.refresh_btn)

        # Right Header: Apply (suggested-action), Align, Identify
        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.set_tooltip_text("Save layout to KDL & reload Niri live")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self.on_apply_clicked)
        header.pack_end(self.apply_btn)

        self.align_btn = Gtk.Button.new_from_icon_name("object-flip-horizontal-symbolic")
        self.align_btn.set_tooltip_text("Auto-align monitors side-by-side")
        self.align_btn.connect("clicked", self.on_align_clicked)
        header.pack_end(self.align_btn)

        self.identify_btn = Gtk.Button.new_from_icon_name("dialog-information-symbolic")
        self.identify_btn.set_tooltip_text("Identify displays (show OSD popups)")
        self.identify_btn.connect("clicked", self.on_identify_clicked)
        header.pack_end(self.identify_btn)

        main_box.append(header)
        main_box.append(self.view_stack)

        # ══════════════════════════════════════════════════════════════════════
        # TAB 1: EINFACH (Simple / Visual Arrangement & Basic Options)
        # ══════════════════════════════════════════════════════════════════════
        scrolled_simple = Gtk.ScrolledWindow()
        scrolled_simple.set_vexpand(True)
        scrolled_simple.set_hexpand(True)

        clamp_simple = Adw.Clamp()
        clamp_simple.set_maximum_size(940)
        clamp_simple.set_tightening_threshold(700)
        scrolled_simple.set_child(clamp_simple)

        simple_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        simple_content.set_margin_top(16)
        simple_content.set_margin_bottom(24)
        simple_content.set_margin_start(16)
        simple_content.set_margin_end(16)
        clamp_simple.set_child(simple_content)

        # ── 1. Interactive Canvas Group ───────────────────────────────────────
        canvas_group = Adw.PreferencesGroup()
        canvas_group.set_title("Spatial Arrangement")
        canvas_group.set_description("Drag & drop displays to arrange. Edges snap magnetically to prevent gaps.")

        canvas_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.canvas = MonitorCanvas(
            on_selection_changed=self.on_canvas_selection_changed,
            on_layout_changed=self.on_canvas_layout_changed
        )
        canvas_card.append(self.canvas)

        # Sub-bar below canvas
        sub_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sub_bar.set_margin_top(4)

        self.selection_label = Gtk.Label(label="Select a display on the canvas...", xalign=0)
        self.selection_label.set_hexpand(True)
        sub_bar.append(self.selection_label)

        self.primary_btn = Gtk.Button(label="★ Set as Primary")
        self.primary_btn.set_tooltip_text("Set selected display as primary monitor")
        self.primary_btn.connect("clicked", self.on_make_primary_clicked)
        sub_bar.append(self.primary_btn)

        canvas_card.append(sub_bar)
        canvas_group.add(canvas_card)
        simple_content.append(canvas_group)

        # ── 2. Simple Controls Group ──────────────────────────────────────────
        self.simple_group = Adw.PreferencesGroup()
        self.simple_group.set_title("Display Settings")
        self.simple_group.set_description("Essential display options for the selected screen.")

        # Auflösung (Sauber gruppiert nach gängigen Auflösungen)
        self.res_row = Adw.ComboRow()
        self.res_row.set_title("Resolution")
        self.res_row.set_subtitle("Physical display resolution")
        self.res_row.connect("notify::selected", self.on_simple_res_selected)
        self.simple_group.add(self.res_row)

        # Skalierung
        self.scale_options = ["100%", "125%", "150%", "175%", "200%"]
        self.scale_row = Adw.ComboRow()
        self.scale_row.set_title("Scaling")
        self.scale_row.set_subtitle("Scale window contents and text for sharper readability")
        self.scale_row.set_model(Gtk.StringList.new(self.scale_options))
        self.scale_row.connect("notify::selected", self.on_scale_selected)
        self.simple_group.add(self.scale_row)

        # Ausrichtung (Einfach: Querformat vs. Hochformat)
        self.orient_options = ["Landscape (Normal 0°)", "Portrait (Right 90°)", "Portrait (Left 270°)"]
        self.orient_values = ["Normal", "90", "270"]
        self.orient_row = Adw.ComboRow()
        self.orient_row.set_title("Orientation")
        self.orient_row.set_subtitle("Landscape for standard monitors or portrait for code and documents")
        self.orient_row.set_model(Gtk.StringList.new(self.orient_options))
        self.orient_row.connect("notify::selected", self.on_orient_selected)
        self.simple_group.add(self.orient_row)

        # Hauptmonitor-Schalter
        self.primary_switch = Adw.SwitchRow()
        self.primary_switch.set_title("Primary Display")
        self.primary_switch.set_subtitle("Default display for notifications and new workspaces")
        self.primary_switch.connect("notify::active", self.on_primary_switch_toggled)
        self.simple_group.add(self.primary_switch)

        simple_content.append(self.simple_group)

        # Add Tab 1 to ViewStack
        page_simple = self.view_stack.add_titled(scrolled_simple, "simple", "Simple")
        page_simple.set_icon_name("video-display-symbolic")

        # ══════════════════════════════════════════════════════════════════════
        # TAB 2: ERWEITERT (Advanced / Precise Coordinates, Hertz & KDL)
        # ══════════════════════════════════════════════════════════════════════
        scrolled_adv = Gtk.ScrolledWindow()
        scrolled_adv.set_vexpand(True)
        scrolled_adv.set_hexpand(True)

        clamp_adv = Adw.Clamp()
        clamp_adv.set_maximum_size(940)
        clamp_adv.set_tightening_threshold(700)
        scrolled_adv.set_child(clamp_adv)

        adv_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        adv_content.set_margin_top(16)
        adv_content.set_margin_bottom(24)
        adv_content.set_margin_start(16)
        adv_content.set_margin_end(16)
        clamp_adv.set_child(adv_content)

        # ── 1. Exakte Geometrie & Positionierung ──────────────────────────────
        geo_group = Adw.PreferencesGroup()
        geo_group.set_title("Pixel-Perfect Coordinates")
        geo_group.set_description("Direct coordinate placement in logical Wayland desktop space.")

        pos_row = Adw.ActionRow()
        pos_row.set_title("Logical Position (X / Y)")
        pos_row.set_subtitle("Manual fine-tuning prevents gaps or cursor trapping")

        coords_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        coords_box.set_valign(Gtk.Align.CENTER)

        lbl_x = Gtk.Label(label="X:")
        coords_box.append(lbl_x)
        self.spin_x = Gtk.SpinButton.new_with_range(-10000, 20000, 10)
        self.spin_x.connect("value-changed", self.on_coord_spin_changed)
        coords_box.append(self.spin_x)

        lbl_y = Gtk.Label(label="Y:")
        coords_box.append(lbl_y)
        self.spin_y = Gtk.SpinButton.new_with_range(-10000, 20000, 10)
        self.spin_y.connect("value-changed", self.on_coord_spin_changed)
        coords_box.append(self.spin_y)

        pos_row.add_suffix(coords_box)
        geo_group.add(pos_row)

        # Erweiterte Drehung (inklusive 180° Überkopf)
        self.adv_tf_options = ["Normal (0°)", "90° (Right)", "180° (Inverted)", "270° (Left)"]
        self.adv_tf_values = ["Normal", "90", "180", "270"]
        self.adv_tf_row = Adw.ComboRow()
        self.adv_tf_row.set_title("Advanced Rotation & Invert")
        self.adv_tf_row.set_subtitle("Supports 180° ceiling or custom arm mount orientation")
        self.adv_tf_row.set_model(Gtk.StringList.new(self.adv_tf_options))
        self.adv_tf_row.connect("notify::selected", self.on_adv_tf_selected)
        geo_group.add(self.adv_tf_row)

        adv_content.append(geo_group)

        # ── 2. Detaillierte Hardware-Modi & Hertz ─────────────────────────────
        rate_group = Adw.PreferencesGroup()
        rate_group.set_title("Refresh Rates & Timings")
        rate_group.set_description("Native hardware video modes including exact fractional refresh rates.")

        self.exact_mode_row = Adw.ComboRow()
        self.exact_mode_row.set_title("Hardware Video Mode")
        self.exact_mode_row.set_subtitle("Exact Niri mode string with millihertz precision")
        self.exact_mode_row.connect("notify::selected", self.on_exact_mode_selected)
        rate_group.add(self.exact_mode_row)

        # Hardware Info Row
        self.hw_info_row = Adw.ActionRow()
        self.hw_info_row.set_title("Hardware Details")
        self.hw_info_badge = Gtk.Label(label="--", css_classes=["caption", "dim-label"])
        self.hw_info_row.add_suffix(self.hw_info_badge)
        rate_group.add(self.hw_info_row)

        adv_content.append(rate_group)

        # ── 3. Niri KDL-Konfiguration & Quelldatei ─────────────────────────────
        kdl_group = Adw.PreferencesGroup()
        kdl_group.set_title("Declarative Niri KDL Configuration")
        target_path = find_config_file(self.custom_config)
        kdl_group.set_description(f"Target file: {target_path}")

        open_row = Adw.ActionRow()
        open_row.set_title("Open configuration file in editor")
        open_row.set_subtitle(target_path)
        open_btn = Gtk.Button(label="Open")
        open_btn.set_valign(Gtk.Align.CENTER)
        open_btn.connect("clicked", lambda b: run_cmd(f"xdg-open {target_path} &"))
        open_row.add_suffix(open_btn)
        kdl_group.add(open_row)

        # Live KDL Code Preview Frame
        preview_group = Adw.PreferencesGroup()
        preview_group.set_title("Live KDL Preview")
        preview_group.set_description("Declarative monitor configuration formatted in Niri KDL syntax")
        self.kdl_preview_view = Gtk.TextView()
        self.kdl_preview_view.set_editable(False)
        self.kdl_preview_view.set_monospace(True)
        self.kdl_preview_view.set_cursor_visible(False)
        self.kdl_preview_view.set_top_margin(10)
        self.kdl_preview_view.set_bottom_margin(10)
        self.kdl_preview_view.set_left_margin(14)
        self.kdl_preview_view.set_right_margin(14)
        self.kdl_preview_view.add_css_class("card")
        self.kdl_preview_buffer = self.kdl_preview_view.get_buffer()

        preview_group.add(self.kdl_preview_view)
        adv_content.append(kdl_group)
        adv_content.append(preview_group)

        # Add Tab 2 to ViewStack
        page_adv = self.view_stack.add_titled(scrolled_adv, "advanced", "Advanced")
        page_adv.set_icon_name("preferences-other-symbolic")

        # Initial Load
        self.load_from_system()

    def show_toast(self, text: str):
        toast = Adw.Toast.new(text)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def load_from_system(self):
        """Query Niri and populate canvas, simple controls, and advanced controls."""
        self._updating = True
        self.monitors = get_monitors()
        self.canvas.set_monitors(self.monitors, force=True)
        self._updating = False

        if self.canvas.selected_port:
            self.on_canvas_selection_changed(self.canvas.selected_port)
        elif self.monitors:
            self.on_canvas_selection_changed(self.monitors[0]["port"])

        self._update_kdl_preview()

    def on_refresh_clicked(self, btn):
        self.load_from_system()
        self.show_toast("Hardware reloaded from Niri.")

    def on_identify_clicked(self, btn):
        identify_monitors(self.canvas.monitors)
        self.show_toast("Identifying displays (OSD overlays dispatched).")

    def on_align_clicked(self, btn):
        self.canvas.auto_align()
        self._update_kdl_preview()
        self.show_toast("Displays aligned horizontally.")

    def on_make_primary_clicked(self, btn):
        if self.canvas.selected_port:
            self.canvas.set_primary_monitor(self.canvas.selected_port)
            self._update_kdl_preview()
            self.show_toast(f"Set {self.canvas.selected_port} as primary display.")

    def on_primary_switch_toggled(self, row, param):
        if self._updating:
            return
        p = self.canvas.selected_port
        if p:
            is_active = self.primary_switch.get_active()
            if is_active:
                self.canvas.set_primary_monitor(p)
            else:
                m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
                if m:
                    m["is_primary"] = False
                    self.canvas.has_unsaved_changes = True
                    self.canvas.queue_draw()
            self._update_kdl_preview()

    def on_apply_clicked(self, btn):
        success, msg = save_monitors_layout(self.canvas.monitors, self.custom_config)
        self.canvas.has_unsaved_changes = False
        self._update_kdl_preview()
        self.show_toast(msg)

    def on_canvas_selection_changed(self, port: str):
        """Sync both Simple and Advanced widgets with the selected monitor."""
        m = next((item for item in self.canvas.monitors if item.get("port") == port), None)
        if not m:
            return

        self._updating = True
        model = m.get("model", port)
        make = m.get("make", "")
        x = m.get("x", 0)
        y = m.get("y", 0)
        w = m.get("width", 0)
        h = m.get("height", 0)
        is_prim = m.get("is_primary", False)
        prim_badge = " ★ [Primary]" if is_prim else ""

        self.selection_label.set_markup(
            f"Selected: <b>{port}</b> ({model}){prim_badge} • Position: <b>X={x}, Y={y}</b> ({w}×{h})"
        )
        self.primary_btn.set_sensitive(not is_prim)
        self.primary_switch.set_active(is_prim)

        # ── Simple View Sync ──────────────────────────────────────────────────
        # Distinct resolutions (without duplicating frequencies)
        modes = m.get("modes", [])
        unique_resolutions = []
        res_labels = []
        for item in modes:
            res_tuple = (item["width"], item["height"])
            if res_tuple not in unique_resolutions:
                unique_resolutions.append(res_tuple)
                tag = ""
                if res_tuple == (3840, 2160):
                    tag = " (4K UHD)"
                elif res_tuple == (2560, 1440):
                    tag = " (2K QHD)"
                elif res_tuple == (1920, 1080):
                    tag = " (Full HD)"
                elif res_tuple == (1920, 1200):
                    tag = " (16:10 WUXGA)"
                res_labels.append(f"{item['width']}×{item['height']}{tag}")

        if not res_labels:
            res_labels = [f"{m.get('width', 1920)}×{m.get('height', 1080)}"]

        self._current_unique_res = unique_resolutions
        self.res_row.set_model(Gtk.StringList.new(res_labels))

        cur_w = m.get("phys_width", 1920)
        cur_h = m.get("phys_height", 1080)
        sel_res_idx = 0
        for i, (rw, rh) in enumerate(unique_resolutions):
            if rw == cur_w and rh == cur_h:
                sel_res_idx = i
                break
        self.res_row.set_selected(sel_res_idx)

        # Simple Scaling
        cur_scale = float(m.get("scale", 1.0))
        cur_scale_pct = f"{int(round(cur_scale * 100))}%"
        scale_idx = 0
        if cur_scale_pct in self.scale_options:
            scale_idx = self.scale_options.index(cur_scale_pct)
        self.scale_row.set_selected(scale_idx)

        # Simple Orientation (Normal, 90, 270)
        tf = str(m.get("transform", "Normal")).strip()
        orient_idx = 0
        if tf in self.orient_values:
            orient_idx = self.orient_values.index(tf)
        self.orient_row.set_selected(orient_idx)

        # ── Advanced View Sync ────────────────────────────────────────────────
        # Exact modes with Hz
        exact_mode_labels = [item.get("label", item.get("mode_str", "")) for item in modes]
        if not exact_mode_labels:
            exact_mode_labels = [m.get("mode", "--")]
        self.exact_mode_row.set_model(Gtk.StringList.new(exact_mode_labels))

        cur_mode = m.get("mode", "")
        exact_idx = 0
        for i, item in enumerate(modes):
            if item.get("mode_str") == cur_mode:
                exact_idx = i
                break
        self.exact_mode_row.set_selected(exact_idx)

        # Coordinate spin buttons
        self.spin_x.set_value(float(x))
        self.spin_y.set_value(float(y))

        # Advanced Rotation
        adv_tf_idx = 0
        if tf in self.adv_tf_values:
            adv_tf_idx = self.adv_tf_values.index(tf)
        self.adv_tf_row.set_selected(adv_tf_idx)

        # Hardware badge
        serial = m.get("serial", "N/A")
        self.hw_info_badge.set_text(f"{make} {model} (S/N: {serial})")

        self._updating = False
        self._update_kdl_preview()

    def on_canvas_layout_changed(self, monitors: List[Dict[str, Any]]):
        """Update spin buttons and status when user moves monitor on canvas."""
        p = self.canvas.selected_port
        if p:
            m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
            if m and not self._updating:
                self._updating = True
                self.spin_x.set_value(float(m.get("x", 0)))
                self.spin_y.set_value(float(m.get("y", 0)))
                self.on_canvas_selection_changed(p)
                self._updating = False
        self._update_kdl_preview()

    def on_simple_res_selected(self, row, param):
        if self._updating:
            return
        p = self.canvas.selected_port
        m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
        if not m:
            return
        idx = row.get_selected()
        if hasattr(self, "_current_unique_res") and 0 <= idx < len(self._current_unique_res):
            rw, rh = self._current_unique_res[idx]
            modes = [item for item in m.get("modes", []) if item["width"] == rw and item["height"] == rh]
            if modes:
                chosen = modes[0]  # Already sorted descending by Hz
                m["mode"] = chosen["mode_str"]
                m["phys_width"] = chosen["width"]
                m["phys_height"] = chosen["height"]
                self._recalculate_dimensions(m)
                self.canvas.has_unsaved_changes = True
                self.canvas.queue_draw()
                self._update_kdl_preview()

    def on_scale_selected(self, row, param):
        if self._updating:
            return
        p = self.canvas.selected_port
        m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
        if not m:
            return
        idx = row.get_selected()
        if 0 <= idx < len(self.scale_options):
            val_pct = self.scale_options[idx]
            scale_f = float(val_pct.rstrip("%")) / 100.0
            m["scale"] = scale_f
            self._recalculate_dimensions(m)
            self.canvas.has_unsaved_changes = True
            self.canvas.queue_draw()
            self._update_kdl_preview()

    def on_orient_selected(self, row, param):
        if self._updating:
            return
        p = self.canvas.selected_port
        m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
        if not m:
            return
        idx = row.get_selected()
        if 0 <= idx < len(self.orient_values):
            tf_code = self.orient_values[idx]
            m["transform"] = tf_code
            self._recalculate_dimensions(m)
            self.canvas.has_unsaved_changes = True
            self.canvas.queue_draw()
            if tf_code in self.adv_tf_values:
                self.adv_tf_row.set_selected(self.adv_tf_values.index(tf_code))
            self._update_kdl_preview()

    def on_adv_tf_selected(self, row, param):
        if self._updating:
            return
        p = self.canvas.selected_port
        m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
        if not m:
            return
        idx = row.get_selected()
        if 0 <= idx < len(self.adv_tf_values):
            tf_code = self.adv_tf_values[idx]
            m["transform"] = tf_code
            self._recalculate_dimensions(m)
            self.canvas.has_unsaved_changes = True
            self.canvas.queue_draw()
            if tf_code in self.orient_values:
                self.orient_row.set_selected(self.orient_values.index(tf_code))
            self._update_kdl_preview()

    def on_exact_mode_selected(self, row, param):
        if self._updating:
            return
        p = self.canvas.selected_port
        m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
        if not m:
            return
        idx = row.get_selected()
        modes = m.get("modes", [])
        if 0 <= idx < len(modes):
            chosen = modes[idx]
            m["mode"] = chosen["mode_str"]
            m["phys_width"] = chosen["width"]
            m["phys_height"] = chosen["height"]
            self._recalculate_dimensions(m)
            self.canvas.has_unsaved_changes = True
            self.canvas.queue_draw()
            self._update_kdl_preview()

    def on_coord_spin_changed(self, spin):
        if self._updating:
            return
        p = self.canvas.selected_port
        m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
        if not m:
            return
        m["x"] = int(round(self.spin_x.get_value()))
        m["y"] = int(round(self.spin_y.get_value()))
        self.canvas.has_unsaved_changes = True
        self.canvas.queue_draw()
        self._update_kdl_preview()

    def _recalculate_dimensions(self, m: Dict[str, Any]):
        """Recalculate logical bounding width and height from physical resolution, transform, and scale."""
        pw = m.get("phys_width", 1920)
        ph = m.get("phys_height", 1080)
        sc = float(m.get("scale", 1.0) or 1.0)
        tf = str(m.get("transform", "Normal")).lower()
        if tf in ["90", "270"]:
            m["width"] = int(round(ph / sc))
            m["height"] = int(round(pw / sc))
        else:
            m["width"] = int(round(pw / sc))
            m["height"] = int(round(ph / sc))

    def _update_kdl_preview(self):
        """Format live KDL preview in the advanced tab."""
        lines = []
        for m in self.canvas.monitors:
            port = m.get("port", "")
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
            lines.append(f'    position x={m.get("x", 0)} y={m.get("y", 0)}')
            lines.append('}\n')
        self.kdl_preview_buffer.set_text("\n".join(lines))
