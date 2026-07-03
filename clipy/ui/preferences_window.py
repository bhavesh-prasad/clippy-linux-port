"""Preferences window (General / Menu / Shortcuts), mirroring Clipy's preference tabs."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


class PreferencesWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Clipy — Preferences")
        self.clipy = app
        self.settings = app.settings
        self.set_default_size(480, 420)
        self._loading = True

        notebook = Gtk.Notebook()
        self.set_child(notebook)
        notebook.append_page(self._general_page(), Gtk.Label(label="General"))
        notebook.append_page(self._menu_page(), Gtk.Label(label="Menu"))
        notebook.append_page(self._shortcut_page(), Gtk.Label(label="Shortcuts"))

        self._loading = False

    # -- page builders ---------------------------------------------------
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
        lbl = Gtk.Label(label=label, xalign=0, hexpand=True)
        row.append(lbl)
        row.append(widget)
        return row

    def _general_page(self) -> Gtk.Box:
        box = self._page()
        box.append(self._row("Number of history items",
                             self._spin(self.settings.max_history, 1, 999, self._set_max_history)))
        box.append(self._row("Store text",
                             self._switch("text" in self.settings.store_types,
                                          lambda v: self._toggle_type("text", v))))
        box.append(self._row("Store images",
                             self._switch("image" in self.settings.store_types,
                                          lambda v: self._toggle_type("image", v))))
        box.append(self._row("Paste automatically after selecting",
                             self._switch(self.settings.paste_after_select,
                                          self._set("paste_after_select"))))
        box.append(self._row("Ignore password-manager entries",
                             self._switch(self.settings.ignore_password_managers,
                                          self._set("ignore_password_managers"))))
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
                             self._switch(self.settings.add_numeric_keys,
                                          self._set("add_numeric_keys", rebuild=True))))
        box.append(self._row("Show snippets inline in menu",
                             self._switch(self.settings.inline_snippets,
                                          self._set("inline_snippets", rebuild=True))))
        return box

    def _shortcut_page(self) -> Gtk.Box:
        box = self._page()
        note = Gtk.Label(
            label="Accelerators use GNOME syntax, e.g. <Control><Alt>v.\n"
                  "Changes register GNOME custom shortcuts.",
            xalign=0, wrap=True)
        note.add_css_class("dim-label")
        box.append(note)
        for key, title in (("history", "Show history"), ("snippets", "Show snippets"),
                           ("menu", "Show menu")):
            entry = Gtk.Entry(text=self.settings.hotkeys.get(key, ""), hexpand=True)
            entry.connect("changed", lambda e, k=key: self._set_hotkey(k, e.get_text()))
            box.append(self._row(title, entry))
        return box

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
        self.settings.store_types = sorted(types)
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
