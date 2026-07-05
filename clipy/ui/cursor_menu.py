"""Native menu shown at the mouse cursor — matches Clipy's hotkey menu.

Clipy's history/snippets hotkey pops a native menu at the pointer: History items
(grouped into folders of ten), Snippets folders as submenus, then Clear History / Edit
Snippets / Preferences / Quit. We reproduce that with a ``Gtk.PopoverMenu`` anchored to a
tiny override-redirect host window placed at the cursor (GTK4 can't position a top-level
on Wayland, but under XWayland the X11 helper can — see :mod:`clipy.x11`).
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib  # noqa: E402

from .. import x11

GROUP_SIZE = 10  # history items per folder, like Clipy's "0 - 9", "10 - 19", …


class CursorMenu:
    def __init__(self, app, kind: str = "full"):
        self.app = app
        self.kind = kind  # "full" | "history" | "snippets"
        self.window = Gtk.Window(decorated=False, resizable=False)
        self.window.set_default_size(1, 1)
        self.window.add_css_class("clipy-cursor-menu-host")
        anchor = Gtk.Box()
        self.window.set_child(anchor)

        self.actions = Gio.SimpleActionGroup()
        self.window.insert_action_group("clipy", self.actions)
        self._n = 0  # unique action id counter
        self._prev_focus = 0        # X window focused before we stole it
        self._pending_paste = False  # set when a history/snippet entry was chosen

        model = self._build_model()
        self.popover = Gtk.PopoverMenu.new_from_model(model)
        self.popover.set_parent(anchor)
        self.popover.set_has_arrow(False)
        self.popover.set_position(Gtk.PositionType.BOTTOM)
        self.popover.set_pointing_to(Gdk.Rectangle())  # 0×0 at the host origin
        self.popover.connect("closed", lambda *_: GLib.idle_add(self._close))

    # -- model -----------------------------------------------------------
    def _add_action(self, callback, is_paste: bool = False) -> str:
        self._n += 1
        name = f"i{self._n}"
        act = Gio.SimpleAction.new(name, None)

        def activate(*_):
            # For history/snippet entries, mark that a paste should follow once the menu
            # has closed and focus has returned (see _close). The callback itself only
            # sets the clipboard now (paste=False), so we control the paste timing.
            if is_paste:
                self._pending_paste = True
            callback()
        act.connect("activate", activate)
        self.actions.add_action(act)
        return f"clipy.{name}"

    def _history_section(self) -> Gio.Menu | None:
        s = self.app.settings
        items = self.app.store.history(s.max_history)
        if not items:
            section = Gio.Menu()
            section.append("(No history)", "clipy.noop")
            return section
        start = 0 if s.number_from_zero else 1
        section = Gio.Menu()
        if len(items) <= GROUP_SIZE:
            for idx, item in enumerate(items):
                section.append(self._label(idx + start, item.preview(s.max_menu_label_length)),
                               self._add_action(lambda it=item: self.app.select_history_item(it, paste=False),
                                                is_paste=True))
        else:
            # Folders of ten, like Clipy (0 - 9, 10 - 19, …).
            for base in range(0, len(items), GROUP_SIZE):
                sub = Gio.Menu()
                for j, item in enumerate(items[base:base + GROUP_SIZE]):
                    sub.append(self._label(j + start, item.preview(s.max_menu_label_length)),
                               self._add_action(lambda it=item: self.app.select_history_item(it, paste=False),
                                                is_paste=True))
                section.append_submenu(f"{base} - {base + GROUP_SIZE - 1}", sub)
        return section

    def _snippets_section(self) -> Gio.Menu | None:
        section = Gio.Menu()
        any_snip = False
        for folder in self.app.store.folders():
            if not folder.enabled:
                continue
            snips = [sn for sn in self.app.store.snippets(folder.id) if sn.enabled]
            if not snips:
                continue
            any_snip = True
            sub = Gio.Menu()
            for sn in snips:
                sub.append(sn.title or "(untitled)",
                           self._add_action(lambda c=sn.content: self.app.paste_text(c, paste=False),
                                            is_paste=True))
            section.append_submenu(folder.name, sub)
        return section if any_snip else None

    def _build_model(self) -> Gio.Menu:
        root = Gio.Menu()
        noop = Gio.SimpleAction.new("noop", None)
        noop.set_enabled(False)
        self.actions.add_action(noop)

        if self.kind in ("full", "history"):
            root.append_section("History", self._history_section())
        if self.kind in ("full", "snippets"):
            snips = self._snippets_section()
            if snips is not None:
                root.append_section("Snippets", snips)

        actions = Gio.Menu()
        if self.app.settings.show_clear_history:
            actions.append("Clear History…", self._add_action(self.app.clear_history))
        actions.append("Edit Snippets…", self._add_action(self.app.show_snippets_manager))
        actions.append("Preferences…", self._add_action(self.app.show_preferences))
        root.append_section(None, actions)

        quit_section = Gio.Menu()
        quit_section.append("Quit Clipy", self._add_action(self.app.quit))
        root.append_section(None, quit_section)
        return root

    @staticmethod
    def _label(number: int, text: str) -> str:
        # Escape underscores so GTK doesn't treat them as mnemonics.
        return f"{number}. {text}".replace("_", "__")

    # -- show at cursor --------------------------------------------------
    def show_at_cursor(self) -> None:
        # Remember who had focus so we can hand it back before pasting.
        self._prev_focus = x11.get_input_focus()
        self.window.realize()
        surface = self.window.get_surface()
        try:
            from gi.repository import GdkX11
            xid = GdkX11.X11Surface.get_xid(surface)
        except Exception:
            xid = 0
        if xid:
            x11.make_override_redirect(xid)
        self.window.present()

        def place():
            pos = x11.pointer_position()
            if xid and pos:
                x11.move_and_focus(xid, pos[0], pos[1])
            self.popover.popup()
            return False
        GLib.timeout_add(20, place)

    # Delay from closing our popup to injecting Ctrl+V. Enough for the compositor to hand
    # keyboard focus back to the target app before the keystroke; tuned empirically (too
    # short races focus-return, too long lets focus drift). ~170ms was reliable in testing.
    PASTE_SETTLE_MS = 170

    def _close(self) -> bool:
        try:
            self.popover.unparent()
        except Exception:
            pass
        # Close our host FIRST, then hand focus back to the app the user was in, and only
        # THEN paste — otherwise the synthesised Ctrl+V lands on us or in a focus gap.
        self.window.close()
        if self._prev_focus:
            x11.set_input_focus(self._prev_focus)
        if self._pending_paste and self.app.wants_auto_paste():
            self._pending_paste = False
            GLib.timeout_add(self.PASTE_SETTLE_MS, self.app.paste_now)
        return False
