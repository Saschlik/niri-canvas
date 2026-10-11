"""
Interactive 2D Canvas for multi-monitor spatial layout with Cairo and GTK4.
Features:
- Proportional physical monitor rendering (stand, bezel, glossy screen)
- Circled display numbering (1, 2, 3, ...)
- Magnetic edge-snapping with neon-cyan guidelines
- Drag-and-drop repositioning with smooth physics
- Primary monitor badge
- Auto-align and coordinate normalization
"""
import math
from typing import Callable, Dict, List, Optional, Tuple, Any

import cairo
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, PangoCairo


def draw_rounded_rect(cr: cairo.Context, x: float, y: float, w: float, h: float, r: float):
    """Draw a rounded rectangle path in Cairo."""
    r = max(1.0, min(r, w / 2.0, h / 2.0))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class MonitorCanvas(Gtk.DrawingArea):
    """
    Interactive 2D spatial canvas displaying proportional monitors.
    """
    def __init__(
        self,
        on_selection_changed: Optional[Callable[[str], None]] = None,
        on_layout_changed: Optional[Callable[[List[Dict[str, Any]]], None]] = None
    ):
        super().__init__()
        self.set_content_height(260)
        self.set_content_width(0)
        self.set_hexpand(True)
        self.set_vexpand(False)

        self.monitors: List[Dict[str, Any]] = []
        self.selected_port: Optional[str] = None
        self.hovered_port: Optional[str] = None
        self.dragged_port: Optional[str] = None
        self.drag_start_mon_x: float = 0.0
        self.drag_start_mon_y: float = 0.0
        self.snap_guides: List[Tuple[str, float]] = []
        self.has_unsaved_changes: bool = False

        self.on_selection_changed = on_selection_changed
        self.on_layout_changed = on_layout_changed

        self.set_draw_func(self.on_draw)

        # Interaction Controllers
        click = Gtk.GestureClick.new()
        click.connect("pressed", self.on_click_pressed)
        self.add_controller(click)

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self.on_mouse_motion)
        motion.connect("leave", self.on_mouse_leave)
        self.add_controller(motion)

    def set_monitors(self, monitors_data: List[Dict[str, Any]], force: bool = False):
        """Update monitor list from backend."""
        if self.has_unsaved_changes and not force:
            return
        self.monitors = [dict(m) for m in monitors_data]
        if self.monitors and (not self.selected_port or not any(m.get("port") == self.selected_port for m in self.monitors)):
            primary = next((m.get("port") for m in self.monitors if m.get("is_primary")), self.monitors[0].get("port"))
            self.selected_port = primary
        self.snap_guides.clear()
        self.queue_draw()

    def get_transform_metrics(self, w: float, h: float) -> Tuple[float, float, float]:
        """Compute scale factor and centering offsets to map desktop pixels to canvas space."""
        if not self.monitors:
            return 0.1, 0.0, 0.0

        min_x = min(m.get("x", 0) for m in self.monitors)
        max_x = max(m.get("x", 0) + m.get("width", 1920) for m in self.monitors)
        min_y = min(m.get("y", 0) for m in self.monitors)
        max_y = max(m.get("y", 0) + m.get("height", 1080) for m in self.monitors)

        world_w = max(100.0, float(max_x - min_x))
        world_h = max(100.0, float(max_y - min_y))

        pad_x = 50.0
        pad_y = 40.0
        avail_w = max(50.0, float(w) - 2 * pad_x)
        avail_h = max(50.0, float(h) - 2 * pad_y)

        scale = min(avail_w / world_w, avail_h / world_h)
        scale = max(0.03, min(scale, 0.20))

        total_w = world_w * scale
        total_h = world_h * scale

        offset_x = (float(w) - total_w) / 2.0 - min_x * scale
        offset_y = (float(h) - total_h) / 2.0 - min_y * scale

        return scale, offset_x, offset_y

    def hit_test(self, px: float, py: float, w: float, h: float) -> Optional[Dict[str, Any]]:
        """Identify monitor under canvas coordinate (px, py)."""
        scale, off_x, off_y = self.get_transform_metrics(w, h)
        for m in reversed(self.monitors):
            bx = m.get("x", 0) * scale + off_x
            by = m.get("y", 0) * scale + off_y
            bw = m.get("width", 1920) * scale
            bh = m.get("height", 1080) * scale
            if bx <= px <= bx + bw and by <= py <= by + bh:
                return m
        return None

    def on_mouse_motion(self, controller, px: float, py: float):
        if self.dragged_port:
            return
        w = self.get_width()
        h = self.get_height()
        hit = self.hit_test(px, py, w, h)
        port = hit.get("port") if hit else None
        if port != self.hovered_port:
            self.hovered_port = port
            if port:
                self.set_cursor_from_name("grab")
            else:
                self.set_cursor_from_name("default")
            self.queue_draw()

    def on_mouse_leave(self, controller):
        if not self.dragged_port:
            self.hovered_port = None
            self.set_cursor_from_name("default")
            self.queue_draw()

    def on_click_pressed(self, gesture, n_press: int, px: float, py: float):
        w = self.get_width()
        h = self.get_height()
        hit = self.hit_test(px, py, w, h)
        if hit:
            self.selected_port = hit.get("port")
            if self.on_selection_changed and self.selected_port:
                self.on_selection_changed(self.selected_port)
            self.queue_draw()

    def on_drag_begin(self, gesture, start_x: float, start_y: float):
        w = self.get_width()
        h = self.get_height()
        hit = self.hit_test(start_x, start_y, w, h)
        if hit:
            self.dragged_port = hit.get("port")
            self.selected_port = self.dragged_port
            self.drag_start_mon_x = float(hit.get("x", 0))
            self.drag_start_mon_y = float(hit.get("y", 0))
            self.snap_guides.clear()
            self.set_cursor_from_name("grabbing")
            if self.on_selection_changed and self.selected_port:
                self.on_selection_changed(self.selected_port)
            self.queue_draw()
        else:
            self.dragged_port = None

    def on_drag_update(self, gesture, offset_x: float, offset_y: float):
        if not self.dragged_port:
            return
        w = self.get_width()
        h = self.get_height()
        scale, off_x, off_y = self.get_transform_metrics(w, h)
        if scale <= 0:
            return

        drag_m = next((m for m in self.monitors if m.get("port") == self.dragged_port), None)
        if not drag_m:
            return

        prop_x = self.drag_start_mon_x + (offset_x / scale)
        prop_y = self.drag_start_mon_y + (offset_y / scale)

        mw = drag_m.get("width", 1920)
        mh = drag_m.get("height", 1080)

        # Magnetic Edge-Snapping threshold: 75 virtual desktop pixels
        SNAP_DIST = 75.0
        snapped_x = prop_x
        snapped_y = prop_y
        new_guides = []

        for other in self.monitors:
            if other.get("port") == self.dragged_port:
                continue
            ox = float(other.get("x", 0))
            oy = float(other.get("y", 0))
            ow = float(other.get("width", 1920))
            oh = float(other.get("height", 1080))

            # Horizontal snapping (Right-to-Left, Left-to-Right, Left-to-Left, Right-to-Right)
            if abs(prop_x - (ox + ow)) < SNAP_DIST:
                snapped_x = ox + ow
                new_guides.append(("v", (ox + ow) * scale + off_x))
            elif abs((prop_x + mw) - ox) < SNAP_DIST:
                snapped_x = ox - mw
                new_guides.append(("v", ox * scale + off_x))
            elif abs(prop_x - ox) < SNAP_DIST:
                snapped_x = ox
                new_guides.append(("v", ox * scale + off_x))
            elif abs((prop_x + mw) - (ox + ow)) < SNAP_DIST:
                snapped_x = ox + ow - mw
                new_guides.append(("v", (ox + ow) * scale + off_x))

            # Vertical snapping (Top-to-Top, Bottom-to-Bottom, Top-to-Bottom, Bottom-to-Top)
            if abs(prop_y - oy) < SNAP_DIST:
                snapped_y = oy
                new_guides.append(("h", oy * scale + off_y))
            elif abs((prop_y + mh) - (oy + oh)) < SNAP_DIST:
                snapped_y = oy + oh - mh
                new_guides.append(("h", (oy + oh) * scale + off_y))
            elif abs(prop_y - (oy + oh)) < SNAP_DIST:
                snapped_y = oy + oh
                new_guides.append(("h", (oy + oh) * scale + off_y))
            elif abs((prop_y + mh) - oy) < SNAP_DIST:
                snapped_y = oy - mh
                new_guides.append(("h", oy * scale + off_y))

        drag_m["x"] = int(round(snapped_x))
        drag_m["y"] = int(round(snapped_y))
        self.snap_guides = new_guides
        self.has_unsaved_changes = True

        if self.on_layout_changed:
            self.on_layout_changed(self.monitors)
        self.queue_draw()

    def on_drag_end(self, gesture, offset_x: float, offset_y: float):
        self.dragged_port = None
        self.snap_guides.clear()
        self.set_cursor_from_name("grab" if self.hovered_port else "default")
        self.queue_draw()

    def auto_align(self):
        """Automatically arrange all monitors seamlessly left-to-right with zero gap."""
        if not self.monitors:
            return
        self.monitors.sort(key=lambda m: (m.get("x", 0), m.get("port", "")))
        cur_x = 0
        for m in self.monitors:
            m["x"] = cur_x
            m["y"] = 0
            cur_x += m.get("width", 1920)
        self.has_unsaved_changes = True
        self.snap_guides.clear()
        if self.on_layout_changed:
            self.on_layout_changed(self.monitors)
        self.queue_draw()

    def set_primary_monitor(self, port: str):
        """Mark selected monitor as primary."""
        for m in self.monitors:
            m["is_primary"] = (m.get("port") == port)
        self.has_unsaved_changes = True
        if self.on_layout_changed:
            self.on_layout_changed(self.monitors)
        self.queue_draw()

    def on_draw(self, widget, cr: cairo.Context, width: int, height: int):
        # 1. Canvas Background: Dark modern radial gradient
        cr.save()
        draw_rounded_rect(cr, 0, 0, width, height, 12)
        cr.clip()

        rad = cairo.RadialGradient(width / 2.0, height / 2.0, 40.0, width / 2.0, height / 2.0, max(width, height) / 1.2)
        rad.add_color_stop_rgb(0.0, 0.08, 0.10, 0.15)
        rad.add_color_stop_rgb(1.0, 0.04, 0.05, 0.08)
        cr.set_source(rad)
        cr.paint()

        # 2. Coordinate Dot Grid
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.04)
        step = 24
        for gx in range(step, int(width), step):
            for gy in range(step, int(height), step):
                cr.arc(gx, gy, 1.1, 0, 2 * math.pi)
                cr.fill()

        # Border
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.10)
        cr.set_line_width(1.0)
        draw_rounded_rect(cr, 0.5, 0.5, width - 1.0, height - 1.0, 12)
        cr.stroke()
        cr.restore()

        if not self.monitors:
            layout = PangoCairo.create_layout(cr)
            layout.set_text("Waiting for display detection from Niri...", -1)
            font_desc = Pango.FontDescription.from_string("Sans 14")
            layout.set_font_description(font_desc)
            cr.set_source_rgba(0.7, 0.7, 0.7, 1.0)
            cr.move_to(20, 30)
            PangoCairo.show_layout(cr, layout)
            return

        scale, off_x, off_y = self.get_transform_metrics(width, height)

        # 3. Draw Magnetic Snap Guidelines (Neon Cyan)
        if self.snap_guides:
            cr.save()
            cr.set_source_rgba(0.22, 0.78, 1.0, 0.85)  # Cyan glow
            cr.set_line_width(1.5)
            cr.set_dash([4.0, 4.0])
            for orient, pos in self.snap_guides:
                if orient == "v":
                    cr.move_to(pos, 10)
                    cr.line_to(pos, height - 10)
                else:
                    cr.move_to(10, pos)
                    cr.line_to(width - 10, pos)
                cr.stroke()
            cr.restore()

        # Order monitors to assign stable indices 1..N based on X coordinate
        sorted_ports = [m.get("port") for m in sorted(self.monitors, key=lambda x: (x.get("x", 0), x.get("port", "")))]

        # 4. Draw Monitors
        for m in self.monitors:
            port = m.get("port", "")
            is_sel = (port == self.selected_port)
            is_drag = (port == self.dragged_port)
            is_hov = (port == self.hovered_port and not is_drag)
            is_prim = m.get("is_primary", False)
            disp_num = (sorted_ports.index(port) + 1) if port in sorted_ports else 1

            bx = m.get("x", 0) * scale + off_x
            by = m.get("y", 0) * scale + off_y
            bw = m.get("width", 1920) * scale
            bh = m.get("height", 1080) * scale

            cr.save()

            # Stand foot below monitor
            foot_w = min(42.0, bw * 0.45)
            foot_h = 7.0
            cr.set_source_rgba(0.18, 0.22, 0.28, 0.85)
            cr.move_to(bx + (bw - foot_w) / 2.0, by + bh)
            cr.line_to(bx + (bw + foot_w) / 2.0, by + bh)
            cr.line_to(bx + (bw + foot_w * 1.3) / 2.0, by + bh + foot_h)
            cr.line_to(bx + (bw - foot_w * 1.3) / 2.0, by + bh + foot_h)
            cr.close_path()
            cr.fill()

            # Soft drop shadow
            if is_drag:
                cr.set_source_rgba(0.0, 0.0, 0.0, 0.50)
                draw_rounded_rect(cr, bx + 2, by + 4, bw, bh, 8)
                cr.fill()

            # Outer Monitor Frame / Bezel
            draw_rounded_rect(cr, bx, by, bw, bh, 8)
            if is_drag:
                cr.set_source_rgba(0.20, 0.40, 0.65, 0.98)
            elif is_sel:
                cr.set_source_rgba(0.15, 0.28, 0.42, 0.96)
            elif is_hov:
                cr.set_source_rgba(0.16, 0.22, 0.30, 0.95)
            else:
                cr.set_source_rgba(0.12, 0.16, 0.22, 0.92)
            cr.fill_preserve()

            # Bezel Highlight / Accent Border
            if is_sel or is_drag:
                cr.set_source_rgb(0.22, 0.78, 1.0)  # Neon Cyan
                cr.set_line_width(2.5)
            elif is_hov:
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.50)
                cr.set_line_width(1.5)
            else:
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.22)
                cr.set_line_width(1.2)
            cr.stroke()

            # Inner Glass Screen
            inner_inset = 4.0
            if bw > 24 and bh > 24:
                draw_rounded_rect(
                    cr,
                    bx + inner_inset,
                    by + inner_inset,
                    bw - 2 * inner_inset,
                    bh - 2 * inner_inset,
                    5.0
                )
                cr.set_source_rgba(0.06, 0.08, 0.12, 0.70)
                cr.fill()

            pango_layout = PangoCairo.create_layout(cr)

            # Display Number Badge (Top-Left)
            badge_r = 9.0
            badge_cx = bx + 16.0
            badge_cy = by + 16.0
            cr.arc(badge_cx, badge_cy, badge_r, 0, 2 * math.pi)
            if is_sel or is_drag:
                cr.set_source_rgb(0.22, 0.78, 1.0)
            else:
                cr.set_source_rgba(0.28, 0.35, 0.46, 0.9)
            cr.fill()

            font_num = Pango.FontDescription.from_string("Sans Bold 8")
            pango_layout.set_font_description(font_num)
            pango_layout.set_text(str(disp_num), -1)
            cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.move_to(badge_cx - 4.0, badge_cy - 6.0)
            PangoCairo.show_layout(cr, pango_layout)

            # Primary Star Badge (Top-Right)
            if is_prim:
                font_badge = Pango.FontDescription.from_string("Sans Bold 7")
                pango_layout.set_font_description(font_badge)
                pango_layout.set_text("★ PRIMARY", -1)
                cr.set_source_rgb(1.0, 0.80, 0.20)  # Amber gold
                cr.move_to(bx + max(28, bw - 60), by + 10)
                PangoCairo.show_layout(cr, pango_layout)

            # Port Name
            font_title = Pango.FontDescription.from_string("Sans Bold 9")
            pango_layout.set_font_description(font_title)
            pango_layout.set_text(port, -1)
            cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.move_to(bx + 30.0, by + 10.0)
            PangoCairo.show_layout(cr, pango_layout)

            # Resolution & Rotation Subtitle
            font_sub = Pango.FontDescription.from_string("Sans 8")
            pango_layout.set_font_description(font_sub)
            tf_str = str(m.get("transform", "Normal"))
            tf_tag = f" ({tf_str}°)" if tf_str.lower() not in ["normal", "0"] else ""
            res_str = f"{m.get('width', 0)}×{m.get('height', 0)}{tf_tag}"
            pango_layout.set_text(res_str, -1)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.80)
            cr.move_to(bx + 12.0, by + 30.0)
            PangoCairo.show_layout(cr, pango_layout)

            # Refresh Rate & Scale Tag
            if bh > 65:
                hz_val = m.get("hz") or round(m.get("modes", [{}])[0].get("refresh_rate", 60000) / 1000) if m.get("modes") else 60
                tag_str = f"{hz_val}Hz"
                scale_val = float(m.get("scale", 1.0))
                if abs(scale_val - 1.0) > 0.05:
                    tag_str += f" • {int(round(scale_val * 100))}%"
                font_tag = Pango.FontDescription.from_string("Sans 7")
                pango_layout.set_font_description(font_tag)
                pango_layout.set_text(tag_str, -1)
                cr.set_source_rgba(0.45, 0.85, 0.75, 0.9)  # Mint
                cr.move_to(bx + 12.0, by + bh - 28.0)
                PangoCairo.show_layout(cr, pango_layout)

            # Coordinates Tag (Bottom)
            if bh > 50:
                pos_str = f"X={m.get('x', 0)} Y={m.get('y', 0)}"
                font_pos = Pango.FontDescription.from_string("Sans 7")
                pango_layout.set_font_description(font_pos)
                pango_layout.set_text(pos_str, -1)
                cr.set_source_rgba(0.65, 0.80, 0.95, 0.85)
                cr.move_to(bx + 12.0, by + bh - 15.0)
                PangoCairo.show_layout(cr, pango_layout)

            cr.restore()
