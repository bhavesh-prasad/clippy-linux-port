"""Compact popup shown at the mouse cursor — the Clipy-style quick chooser.

Appears where the pointer is (via the X11 helper, since we run under XWayland), narrow
and keyboard-driven: type to filter, Up/Down to move, Enter to paste, 1-9 quick pick,
Delete to remove (history only), Esc to close. Closes when it loses focus.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402

from .. import x11

POPUP_WIDTH = 320
POPUP_MAX_HEIGHT = 420


class CursorPopup(Gtk.Window):
    """Base compact popup. Subclasses provide rows and the activation action."""

    def __init__(self, app, title: str, placeholder: str):
        super().__init__(title=title)
        self.clipy = app
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(POPUP_WIDTH, -1)
        self.add_css_class("clipy-popup")

        outer = Gtk.Frame()
        outer.add_css_class("clipy-popup-frame")
        self.set_child(outer)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_child(box)

        self.search = Gtk.SearchEntry(placeholder_text=placeholder)
        self.search.set_margin_top(6); self.search.set_margin_bottom(6)
        self.search.set_margin_start(6); self.search.set_margin_end(6)
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        self.search.connect("activate", lambda *_: self._activate_selected())
        box.append(self.search)

        self.scroller = Gtk.ScrolledWindow(vexpand=True)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_max_content_height(POPUP_MAX_HEIGHT)
        self.scroller.set_propagate_natural_height(True)
        box.append(self.scroller)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("clipy-popup-list")
        self.listbox.set_filter_func(self._filter_row)
        self.listbox.connect("row-activated", lambda _lb, row: self._activate_row(row))
        self.scroller.set_child(self.listbox)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._on_focus_leave())
        self.add_controller(focus)

        self._install_css()
        self.populate()

    # -- to override -----------------------------------------------------
    def populate(self) -> None:
        raise NotImplementedError

    def _activate_row(self, row) -> None:
        raise NotImplementedError

    # -- shared row helpers ---------------------------------------------
    def _clear(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

    def _select_first(self) -> None:
        first = self.listbox.get_row_at_index(0)
        if first:
            self.listbox.select_row(first)

    # -- show at cursor --------------------------------------------------
    def show_at_cursor(self) -> None:
        self.realize()
        surface = self.get_surface()
        try:
            from gi.repository import GdkX11
            xid = GdkX11.X11Surface.get_xid(surface)
        except Exception:
            xid = 0
        if xid:
            x11.make_override_redirect(xid)
        self.present()

        def place():
            pos = x11.pointer_position()
            if xid and pos:
                x, y = self._clamp_to_monitor(pos[0] + 2, pos[1] + 2)
                x11.move_and_focus(xid, x, y)
            self.search.grab_focus()
            return False
        GLib.timeout_add(20, place)

    def _clamp_to_monitor(self, x: int, y: int) -> tuple[int, int]:
        display = Gdk.Display.get_default()
        width = self.get_width() or POPUP_WIDTH
        height = min(self.get_height() or POPUP_MAX_HEIGHT, POPUP_MAX_HEIGHT)
        try:
            monitors = display.get_monitors()
            geo = None
            for i in range(monitors.get_n_items()):
                m = monitors.get_item(i)
                g = m.get_geometry()
                if g.x <= x <= g.x + g.width and g.y <= y <= g.y + g.height:
                    geo = g; break
            if geo is None and monitors.get_n_items():
                geo = monitors.get_item(0).get_geometry()
            if geo is not None:
                if x + width > geo.x + geo.width:
                    x = max(geo.x, geo.x + geo.width - width)
                if y + height > geo.y + geo.height:
                    y = max(geo.y, geo.y + geo.height - height)
        except Exception:
            pass
        return x, y

    # -- filtering / keyboard -------------------------------------------
    def _filter_row(self, row) -> bool:
        text = self.search.get_text().strip().lower()
        return not text or text in getattr(row, "search_text", "")

    def _visible_rows(self):
        rows = []
        i = 0
        while (r := self.listbox.get_row_at_index(i)) is not None:
            if self._filter_row(r):
                rows.append(r)
            i += 1
        return rows

    def _on_key(self, _c, keyval, _kc, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close(); return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
            rows = self._visible_rows()
            if rows:
                cur = self.listbox.get_selected_row()
                idx = rows.index(cur) if cur in rows else -1
                idx = max(0, min(len(rows) - 1, idx + (1 if keyval == Gdk.KEY_Down else -1)))
                self.listbox.select_row(rows[idx]); rows[idx].grab_focus()
            return True
        if Gdk.KEY_1 <= keyval <= Gdk.KEY_9 and not self.search.get_text():
            rows = self._visible_rows()
            i = keyval - Gdk.KEY_1
            if i < len(rows):
                self._activate_row(rows[i])
            return True
        return False

    def _activate_selected(self) -> None:
        row = self.listbox.get_selected_row() or (self._visible_rows() or [None])[0]
        if row:
            self._activate_row(row)

    def _on_focus_leave(self) -> None:
        # Close shortly after losing focus (ignore transient focus moves within).
        GLib.timeout_add(120, self._maybe_close)

    def _maybe_close(self) -> bool:
        if not self.is_active():
            self.close()
        return False

    def _install_css(self) -> None:
        if getattr(CursorPopup, "_css_done", False):
            return
        css = Gtk.CssProvider()
        css.load_from_data(b"""
        .clipy-popup-frame { border-radius: 8px; }
        .clipy-popup-list row { padding: 2px 6px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        CursorPopup._css_done = True


class HistoryPopup(CursorPopup):
    def __init__(self, app):
        super().__init__(app, "Clipy — History", "Search history…")

    def populate(self) -> None:
        self._clear()
        s = self.clipy.settings
        start = 0 if getattr(s, "number_from_zero", False) else 1
        items = self.clipy.store.history(s.menu_history_count)
        for idx, item in enumerate(items):
            row = Gtk.ListBoxRow()
            row.item = item
            row.search_text = item.preview(200).lower()
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            hb.set_margin_top(3); hb.set_margin_bottom(3)
            hb.set_margin_start(6); hb.set_margin_end(6)
            if s.add_numeric_keys and idx < 9:
                num = Gtk.Label(label=str(idx + start)); num.add_css_class("dim-label")
                num.set_xalign(0.5); num.set_size_request(14, -1)
                hb.append(num)
            icon = Gtk.Image.new_from_icon_name(
                "image-x-generic" if item.kind == "image" else "text-x-generic")
            hb.append(icon)
            label = Gtk.Label(label=item.preview(60), xalign=0, hexpand=True)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            hb.append(label)
            row.set_child(hb)
            self.listbox.append(row)
        self._select_first()

    def _on_key(self, c, keyval, kc, state) -> bool:
        if keyval == Gdk.KEY_Delete:
            row = self.listbox.get_selected_row()
            if row and getattr(row, "item", None):
                self.clipy.store.delete_history(row.item.id)
                self.clipy.rebuild_menu()
                self.populate()
            return True
        return super()._on_key(c, keyval, kc, state)

    def _activate_row(self, row) -> None:
        item = getattr(row, "item", None)
        if item is not None:
            self.close()
            self.clipy.select_history_item(item)


class SnippetPopup(CursorPopup):
    def __init__(self, app):
        super().__init__(app, "Clipy — Snippets", "Search snippets…")

    def populate(self) -> None:
        self._clear()
        for folder in self.clipy.store.folders():
            if not folder.enabled:
                continue
            for snip in self.clipy.store.snippets(folder.id):
                if not snip.enabled:
                    continue
                row = Gtk.ListBoxRow()
                row.content = snip.content
                row.search_text = f"{folder.name} {snip.title} {snip.content}".lower()
                lbl = Gtk.Label(label=f"{folder.name}  ›  {snip.title or '(untitled)'}",
                                xalign=0, margin_top=3, margin_bottom=3,
                                margin_start=8, margin_end=8)
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                row.set_child(lbl)
                self.listbox.append(row)
        self._select_first()

    def _activate_row(self, row) -> None:
        content = getattr(row, "content", None)
        if content is not None:
            self.close()
            self.clipy.paste_text(content)
