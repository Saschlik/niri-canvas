"""
Libadwaita User Interface for Niri Canvas.
Provides a modern GNOME desktop experience with HeaderBar, Canvas, Inspector, and Toasts.
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
        self.set_default_size(980, 720)
        self.set_size_request(600, 500)

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
        title_widget = Adw.WindowTitle(title="Niri Canvas", subtitle="Visual Multi-Monitor Manager")
        header.set_title_widget(title_widget)

        # Left Header items: Refresh
        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_btn.set_tooltip_text("Hardware neu einlesen & Änderungen verwerfen")
        self.refresh_btn.connect("clicked", self.on_refresh_clicked)
        header.pack_start(self.refresh_btn)

        # Right Header items: Identify, Auto-Align, Apply, Menu
        self.apply_btn = Gtk.Button(label="Anwenden")
        self.apply_btn.set_tooltip_text("Layout in KDL speichern & Niri live aktualisieren")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self.on_apply_clicked)
        header.pack_end(self.apply_btn)

        self.align_btn = Gtk.Button.new_from_icon_name("object-flip-horizontal-symbolic")
        self.align_btn.set_tooltip_text("Monitore automatisch lückenlos anordnen")
        self.align_btn.connect("clicked", self.on_align_clicked)
        header.pack_end(self.align_btn)

        self.identify_btn = Gtk.Button.new_from_icon_name("dialog-information-symbolic")
        self.identify_btn.set_tooltip_text("Displays identifizieren (Nummern & Ports anzeigen)")
        self.identify_btn.connect("clicked", self.on_identify_clicked)
        header.pack_end(self.identify_btn)

        main_box.append(header)

        # ── Scrollable Body ───────────────────────────────────────────────────
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        main_box.append(scrolled)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(960)
        clamp.set_tightening_threshold(700)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(24)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        clamp.set_child(content_box)

        # ── 1. Interactive Canvas Group ───────────────────────────────────────
        canvas_group = Adw.PreferencesGroup()
        canvas_group.set_title("Räumliche Anordnung")
        canvas_group.set_description("Monitore per Drag & Drop verschieben. Kanten docken magnetisch aneinander an.")

        canvas_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.canvas = MonitorCanvas(
            on_selection_changed=self.on_canvas_selection_changed,
            on_layout_changed=self.on_canvas_layout_changed
        )
        canvas_card.append(self.canvas)

        # Canvas Sub-bar (Selection details & Primary button)
        sub_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sub_bar.set_margin_top(4)

        self.selection_label = Gtk.Label(label="Wähle einen Monitor auf dem Canvas...", xalign=0)
        self.selection_label.set_hexpand(True)
        sub_bar.append(self.selection_label)

        self.primary_btn = Gtk.Button(label="★ Als Hauptmonitor")
        self.primary_btn.set_tooltip_text("Ausgewählten Monitor als Hauptbildschirm markieren")
        self.primary_btn.connect("clicked", self.on_make_primary_clicked)
        sub_bar.append(self.primary_btn)

        canvas_card.append(sub_bar)
        canvas_group.add(canvas_card)
        content_box.append(canvas_group)

        # ── 2. Inspector Group (Settings for Selected Display) ────────────────
        self.inspector_group = Adw.PreferencesGroup()
        self.inspector_group.set_title("Monitor-Eigenschaften")
        self.inspector_group.set_description("Auflösung, Skalierung und Drehung des ausgewählten Displays anpassen.")

        # Mode row (Resolution + Refresh Rate)
        self.mode_row = Adw.ComboRow()
        self.mode_row.set_title("Auflösung & Bildwiederholrate")
        self.mode_row.set_subtitle("Unterstützte Hardware-Modi")
        self.mode_row.connect("notify::selected", self.on_mode_selected)
        self.inspector_group.add(self.mode_row)

        # Scale row
        self.scale_options = ["100%", "125%", "150%", "175%", "200%"]
        self.scale_row = Adw.ComboRow()
        self.scale_row.set_title("Skalierung")
        self.scale_row.set_subtitle("Fraktionale Benutzeroberflächen-Skalierung")
        self.scale_row.set_model(Gtk.StringList.new(self.scale_options))
        self.scale_row.connect("notify::selected", self.on_scale_selected)
        self.inspector_group.add(self.scale_row)

        # Transform / Rotation row
        self.transform_options = ["Normal (0°)", "90° (Rechts)", "180° (Überkopf)", "270° (Links)"]
        self.transform_values = ["Normal", "90", "180", "270"]
        self.transform_row = Adw.ComboRow()
        self.transform_row.set_title("Ausrichtung / Drehung")
        self.transform_row.set_subtitle("Dreht das Display im Raum")
        self.transform_row.set_model(Gtk.StringList.new(self.transform_options))
        self.transform_row.connect("notify::selected", self.on_transform_selected)
        self.inspector_group.add(self.transform_row)

        # Coordinate Fine-Tuning Row
        pos_row = Adw.ActionRow()
        pos_row.set_title("Pixel-genaue Position (X / Y)")
        pos_row.set_subtitle("Feinabstimmung der logischen Desktop-Koordinaten")

        coords_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
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
        self.inspector_group.add(pos_row)

        content_box.append(self.inspector_group)

        # ── 3. Target Config Information ──────────────────────────────────────
        self.config_group = Adw.PreferencesGroup()
        self.config_group.set_title("Niri Konfiguration")
        target_path = find_config_file(self.custom_config)
        self.config_group.set_description(f"Ziel: {target_path}")

        open_cfg_row = Adw.ActionRow()
        open_cfg_row.set_title("Konfigurationsdatei im Texteditor öffnen")
        open_cfg_row.set_subtitle(target_path)
        open_btn = Gtk.Button(label="Öffnen")
        open_btn.set_valign(Gtk.Align.CENTER)
        open_btn.connect("clicked", lambda b: run_cmd(f"xdg-open {target_path} &"))
        open_cfg_row.add_suffix(open_btn)
        self.config_group.add(open_cfg_row)

        content_box.append(self.config_group)

        # Initial Load
        self.load_from_system()

    def show_toast(self, text: str):
        toast = Adw.Toast.new(text)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def load_from_system(self):
        """Query Niri and populate canvas and inspector."""
        self._updating = True
        self.monitors = get_monitors()
        self.canvas.set_monitors(self.monitors, force=True)
        self._updating = False

        if self.canvas.selected_port:
            self.on_canvas_selection_changed(self.canvas.selected_port)
        elif self.monitors:
            self.on_canvas_selection_changed(self.monitors[0]["port"])

    def on_refresh_clicked(self, btn):
        self.load_from_system()
        self.show_toast("Hardware-Status neu eingelesen.")

    def on_identify_clicked(self, btn):
        identify_monitors(self.canvas.monitors)
        self.show_toast("Displays werden identifiziert (Benachrichtigungen gesendet).")

    def on_align_clicked(self, btn):
        self.canvas.auto_align()
        self.show_toast("Monitore automatisch nebeneinander angeordnet.")

    def on_make_primary_clicked(self, btn):
        if self.canvas.selected_port:
            self.canvas.set_primary_monitor(self.canvas.selected_port)
            self.show_toast(f"{self.canvas.selected_port} als Hauptmonitor festgelegt.")

    def on_apply_clicked(self, btn):
        success, msg = save_monitors_layout(self.canvas.monitors, self.custom_config)
        self.canvas.has_unsaved_changes = False
        self.show_toast(msg)

    def on_canvas_selection_changed(self, port: str):
        """Sync Inspector widgets with selected monitor."""
        m = next((item for item in self.canvas.monitors if item.get("port") == port), None)
        if not m:
            return

        self._updating = True
        model = m.get("model", port)
        x = m.get("x", 0)
        y = m.get("y", 0)
        w = m.get("width", 0)
        h = m.get("height", 0)
        is_prim = m.get("is_primary", False)
        prim_badge = " ★ [Hauptmonitor]" if is_prim else ""

        self.selection_label.set_markup(
            f"Ausgewählt: <b>{port}</b> ({model}){prim_badge} • Position: <b>X={x}, Y={y}</b> ({w}×{h})"
        )
        self.primary_btn.set_sensitive(not is_prim)

        # Modes dropdown
        modes = m.get("modes", [])
        mode_labels = [item.get("label", item.get("mode_str", "")) for item in modes]
        if not mode_labels:
            mode_labels = [m.get("mode", "--")]
        self.mode_row.set_model(Gtk.StringList.new(mode_labels))

        cur_mode = m.get("mode", "")
        sel_idx = 0
        for i, item in enumerate(modes):
            if item.get("mode_str") == cur_mode:
                sel_idx = i
                break
        self.mode_row.set_selected(sel_idx)

        # Scale dropdown
        cur_scale = float(m.get("scale", 1.0))
        cur_scale_pct = f"{int(round(cur_scale * 100))}%"
        scale_idx = 0
        if cur_scale_pct in self.scale_options:
            scale_idx = self.scale_options.index(cur_scale_pct)
        self.scale_row.set_selected(scale_idx)

        # Transform dropdown
        tf = str(m.get("transform", "Normal")).strip()
        tf_idx = 0
        if tf in self.transform_values:
            tf_idx = self.transform_values.index(tf)
        self.transform_row.set_selected(tf_idx)

        # Spin buttons
        self.spin_x.set_value(float(x))
        self.spin_y.set_value(float(y))

        self._updating = False

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

    def on_mode_selected(self, row, param):
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

    def on_transform_selected(self, row, param):
        if self._updating:
            return
        p = self.canvas.selected_port
        m = next((item for item in self.canvas.monitors if item.get("port") == p), None)
        if not m:
            return
        idx = row.get_selected()
        if 0 <= idx < len(self.transform_values):
            tf_code = self.transform_values[idx]
            m["transform"] = tf_code
            self._recalculate_dimensions(m)
            self.canvas.has_unsaved_changes = True
            self.canvas.queue_draw()

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
