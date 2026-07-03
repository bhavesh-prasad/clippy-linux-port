"""Searchable clipboard-history popup — the target of the history hotkey.

Wayland cannot position a popup under the pointer, so we show a centered, keyboard-driven
window instead: type to filter, Up/Down to move, Enter to paste, 1-9 for quick pick,
Delete to remove an entry, Esc to close.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402


class HistoryWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Clipy — History")
        self.clipy = app
        self.set_default_size(460, 420)
        self.set_resizable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(box)

        self.search = Gtk.SearchEntry(placeholder_text="Search history…")
        self.search.set_margin_top(8)
        self.search.set_margin_bottom(8)
        self.search.set_margin_start(8)
        self.search.set_margin_end(8)
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        self.search.connect("activate", lambda *_: self._activate_selected())
        box.append(self.search)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.append(scroller)

        self.listbox = Gtk.ListBox()
        self.listbox.set_filter_func(self._filter_row)
        self.listbox.connect("row-activated", lambda _lb, row: self._paste_row(row))
        scroller.set_child(self.listbox)

        # Keyboard handling: forward navigation from the search entry to the list.
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        self.populate()

    def populate(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

        items = self.clipy.store.history(self.clipy.settings.max_history)
        for idx, item in enumerate(items):
            row = Gtk.ListBoxRow()
            row.item = item  # type: ignore[attr-defined]
            row.search_text = item.preview(200).lower()  # type: ignore[attr-defined]
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hb.set_margin_top(6)
            hb.set_margin_bottom(6)
            hb.set_margin_start(10)
            hb.set_margin_end(10)
            if idx < 9:
                num = Gtk.Label(label=str(idx + 1))
                num.add_css_class("dim-label")
                num.set_size_request(16, -1)
                hb.append(num)
            icon = Gtk.Image.new_from_icon_name(
                "image-x-generic" if item.kind == "image" else "text-x-generic")
            hb.append(icon)
            label = Gtk.Label(label=item.preview(80), xalign=0, hexpand=True)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            hb.append(label)
            row.set_child(hb)
            self.listbox.append(row)

        first = self.listbox.get_row_at_index(0)
        if first:
            self.listbox.select_row(first)

    # -- filtering -------------------------------------------------------
    def _filter_row(self, row: Gtk.ListBoxRow) -> bool:
        text = self.search.get_text().strip().lower()
        if not text:
            return True
        return text in getattr(row, "search_text", "")

    # -- keyboard --------------------------------------------------------
    def _on_key(self, _ctrl, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            self._move(1 if keyval == Gdk.KEY_Down else -1)
            return True
        # 1-9 quick pick (only when not typing into a populated search box)
        if Gdk.KEY_1 <= keyval <= Gdk.KEY_9 and not self.search.get_text():
            self._paste_index(keyval - Gdk.KEY_1)
            return True
        if keyval == Gdk.KEY_Delete:
            self._delete_selected()
            return True
        return False

    def _visible_rows(self) -> list[Gtk.ListBoxRow]:
        rows = []
        i = 0
        while True:
            r = self.listbox.get_row_at_index(i)
            if r is None:
                break
            if r.get_child_visible() and self._filter_row(r):
                rows.append(r)
            i += 1
        return rows

    def _move(self, delta: int) -> None:
        rows = self._visible_rows()
        if not rows:
            return
        cur = self.listbox.get_selected_row()
        idx = rows.index(cur) if cur in rows else -1
        idx = max(0, min(len(rows) - 1, idx + delta))
        self.listbox.select_row(rows[idx])
        rows[idx].grab_focus()

    def _activate_selected(self) -> None:
        row = self.listbox.get_selected_row() or (self._visible_rows() or [None])[0]
        if row:
            self._paste_row(row)

    def _paste_index(self, index: int) -> None:
        rows = self._visible_rows()
        if 0 <= index < len(rows):
            self._paste_row(rows[index])

    def _paste_row(self, row: Gtk.ListBoxRow) -> None:
        item = getattr(row, "item", None)
        if item is not None:
            self.close()
            self.clipy.select_history_item(item)

    def _delete_selected(self) -> None:
        row = self.listbox.get_selected_row()
        if not row:
            return
        item = getattr(row, "item", None)
        if item is not None:
            self.clipy.store.delete_history(item.id)
            self.clipy.rebuild_menu()
            self.populate()
