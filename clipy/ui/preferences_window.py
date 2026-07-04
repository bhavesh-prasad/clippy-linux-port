"""Preferences window, mirroring Clipy's tabs: General, Menu, Type, Shortcuts, Applications."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..config import ALL_STORE_TYPES, STORE_TYPE_LABELS


class PreferencesWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Clipy — Preferences")
        self.clipy = app
        self.settings = app.settings
        self.set_default_size(520, 460)
        self._loading = True

        notebook = Gtk.Notebook()
        self.set_child(notebook)
        notebook.append_page(self._general_page(), Gtk.Label(label="General"))
        notebook.append_page(self._menu_page(), Gtk.Label(label="Menu"))
        notebook.append_page(self._type_page(), Gtk.Label(label="Type"))
        notebook.append_page(self._shortcut_page(), Gtk.Label(label="Shortcuts"))
        notebook.append_page(self._applications_page(), Gtk.Label(label="Applications"))

        self._loading = False

    # -- widget helpers --------------------------------------------------
    def _page(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(16); box.set_margin_end(16)
        return box

    def _spin(self, value, lo, hi, on_change) -> Gtk.SpinButton:
        adj = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=1)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        spin.connect("value-changed", lambda s: on_change(int(s.get_value())))
        return spin

    def _switch(self, active, on_change) -> Gtk.Switch:
        sw = Gtk.Switch(active=active, halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        sw.connect("notify::active", lambda s, _p: on_change(s.get_active()))
        return sw

    def _row(self, label, widget) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.append(Gtk.Label(label=label, xalign=0, hexpand=True))
        row.append(widget)
        return row

    # -- pages -----------------------------------------------------------
    def _general_page(self) -> Gtk.Box:
        box = self._page()
        box.append(self._row("Number of history items",
                             self._spin(self.settings.max_history, 1, 999, self._set_max_history)))
        box.append(self._row("Paste automatically after selecting",
                             self._switch(self.settings.paste_after_select, self._set("paste_after_select"))))
        box.append(self._row("Move item to top after pasting",
                             self._switch(self.settings.reorder_after_paste, self._set("reorder_after_paste"))))
        box.append(self._row("Ignore password-manager entries",
                             self._switch(self.settings.ignore_password_managers, self._set("ignore_password_managers"))))
        box.append(self._row("Confirm before clearing history",
                             self._switch(self.settings.confirm_clear_history, self._set("confirm_clear_history"))))
        box.append(self._row("Confirm before deleting a snippet",
                             self._switch(self.settings.confirm_delete_snippet, self._set("confirm_delete_snippet"))))
        box.append(self._row("Launch at login",
                             self._switch(self.settings.launch_at_login, self._set_login)))
        return box

    def _menu_page(self) -> Gtk.Box:
        box = self._page()
        box.append(self._row("History items shown in menu",
                             self._spin(self.settings.menu_history_count, 1, 100,
                                        self._set("menu_history_count", rebuild=True))))
        box.append(self._row("Max menu label length",
                             self._spin(self.settings.max_menu_label_length, 10, 120,
                                        self._set("max_menu_label_length", rebuild=True))))
        box.append(self._row("Number keys (1-9) on history items",
                             self._switch(self.settings.add_numeric_keys, self._set("add_numeric_keys", rebuild=True))))
        box.append(self._row("Start numbering from 0",
                             self._switch(self.settings.number_from_zero, self._set("number_from_zero", rebuild=True))))
        box.append(self._row("Show type icon in menu",
                             self._switch(self.settings.show_menu_icons, self._set("show_menu_icons", rebuild=True))))
        box.append(self._row("Show image thumbnails in menu",
                             self._switch(self.settings.show_image_thumbnails, self._set("show_image_thumbnails", rebuild=True))))
        box.append(self._row("Show snippets inline in menu",
                             self._switch(self.settings.inline_snippets, self._set("inline_snippets", rebuild=True))))
        box.append(self._row("Show 'Clear History' menu item",
                             self._switch(self.settings.show_clear_history, self._set("show_clear_history", rebuild=True))))
        return box

    def _type_page(self) -> Gtk.Box:
        box = self._page()
        box.append(Gtk.Label(label="Store these clipboard types:", xalign=0))
        for t in ALL_STORE_TYPES:
            box.append(self._row(STORE_TYPE_LABELS[t],
                                 self._switch(t in self.settings.store_types,
                                              lambda on, kind=t: self._toggle_type(kind, on))))
        note = Gtk.Label(
            label="Rich text and file copies are detected from the clipboard's MIME types.",
            xalign=0, wrap=True)
        note.add_css_class("dim-label")
        box.append(note)
        return box

    def _shortcut_page(self) -> Gtk.Box:
        box = self._page()
        note = Gtk.Label(
            label="Accelerators use GNOME syntax, e.g. <Control><Shift>v.\n"
                  "Changes register GNOME custom shortcuts.",
            xalign=0, wrap=True)
        note.add_css_class("dim-label")
        box.append(note)
        for key, title in (("history", "Show history popup"), ("snippets", "Show snippets popup"),
                           ("menu", "Show menu")):
            entry = Gtk.Entry(text=self.settings.hotkeys.get(key, ""), hexpand=True)
            entry.connect("changed", lambda e, k=key: self._set_hotkey(k, e.get_text()))
            box.append(self._row(title, entry))
        return box

    def _applications_page(self) -> Gtk.Box:
        box = self._page()
        box.append(Gtk.Label(
            label="Don't record clipboard changes from these apps (by window class).",
            xalign=0, wrap=True))
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self.exclude_list = Gtk.ListBox()
        scroll.set_child(self.exclude_list)
        box.append(scroll)
        self._reload_excludes()

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.exclude_entry = Gtk.Entry(placeholder_text="Window class, e.g. keepassxc", hexpand=True)
        self.exclude_entry.connect("activate", lambda *_: self._add_exclude())
        entry_row.append(self.exclude_entry)
        add = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add.connect("clicked", lambda *_: self._add_exclude())
        entry_row.append(add)
        box.append(entry_row)

        note = Gtk.Label(
            label="Note: on GNOME Wayland the source app can only be detected for X11/"
                  "XWayland apps; native Wayland apps can't be identified.",
            xalign=0, wrap=True)
        note.add_css_class("dim-label")
        box.append(note)
        return box

    def _reload_excludes(self) -> None:
        child = self.exclude_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling(); self.exclude_list.remove(child); child = nxt
        for name in self.settings.exclude_apps:
            row = Gtk.ListBoxRow()
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                         margin_top=3, margin_bottom=3, margin_start=8, margin_end=6)
            hb.append(Gtk.Label(label=name, xalign=0, hexpand=True))
            rm = Gtk.Button.new_from_icon_name("list-remove-symbolic")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, n=name: self._remove_exclude(n))
            hb.append(rm)
            row.set_child(hb)
            self.exclude_list.append(row)

    def _add_exclude(self) -> None:
        name = self.exclude_entry.get_text().strip()
        if name and name not in self.settings.exclude_apps:
            self.settings.exclude_apps.append(name)
            self.settings.save()
            self.exclude_entry.set_text("")
            self._reload_excludes()

    def _remove_exclude(self, name: str) -> None:
        if name in self.settings.exclude_apps:
            self.settings.exclude_apps.remove(name)
            self.settings.save()
            self._reload_excludes()

    # -- change handlers -------------------------------------------------
    def _set(self, attr, rebuild=False):
        def handler(value):
            if self._loading:
                return
            setattr(self.settings, attr, value)
            self.settings.save()
            if rebuild:
                self.clipy.rebuild_menu()
        return handler

    def _set_max_history(self, value: int) -> None:
        if self._loading:
            return
        self.settings.max_history = value
        self.settings.save()
        self.clipy.store.trim_history(value)
        self.clipy.rebuild_menu()

    def _toggle_type(self, kind: str, on: bool) -> None:
        if self._loading:
            return
        types = set(self.settings.store_types)
        types.add(kind) if on else types.discard(kind)
        self.settings.store_types = [t for t in ALL_STORE_TYPES if t in types]
        self.settings.save()

    def _set_login(self, on: bool) -> None:
        if self._loading:
            return
        self.settings.launch_at_login = on
        self.settings.save()
        self.clipy.set_autostart(on)

    def _set_hotkey(self, key: str, accel: str) -> None:
        if self._loading:
            return
        self.settings.hotkeys[key] = accel.strip()
        self.settings.save()
        self.clipy.apply_hotkeys()
