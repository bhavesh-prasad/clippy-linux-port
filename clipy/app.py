"""The Clipy application: wires storage, clipboard, tray menu, windows, and hotkeys.

A single long-running :class:`Gtk.Application` (single-instance). Extra invocations with
``--action`` are routed to the primary instance via GApplication's command-line
forwarding, which is also how global hotkeys reach the running app.
"""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib  # noqa: E402

from . import APP_ID, APP_NAME, config, hotkeys
from .clipboard import ClipboardMonitor
from .storage import Store
from .config import Settings
from .sni.dbusmenu import DbusMenu, MenuItem
from .sni.item import StatusNotifierItem
from .ui.snippet_window import SnippetWindow
from .ui.preferences_window import PreferencesWindow

AUTOSTART_PATH = config._xdg("XDG_CONFIG_HOME", ".config") / "autostart" / "clipy-linux.desktop"


class ClipyApplication(Gtk.Application):
    def __init__(self, launcher_command: str):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.launcher_command = launcher_command
        self.store: Store | None = None
        self.settings: Settings | None = None
        self.monitor: ClipboardMonitor | None = None
        self.dbusmenu: DbusMenu | None = None
        self.sni: StatusNotifierItem | None = None
        self._windows: dict[str, Gtk.Window] = {}
        self._rebuild_pending = False

    # -- lifecycle -------------------------------------------------------
    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        config.ensure_dirs()
        self.settings = Settings.load()
        self.store = Store()
        self.store.seed_default_snippets()
        self.store.trim_history(self.settings.max_history)

        display = Gdk.Display.get_default()
        if display is not None:
            self.monitor = ClipboardMonitor(display, self._on_capture)
            GLib.idle_add(self._capture_initial)

        self._setup_tray()
        self.apply_hotkeys()
        self._setup_injector()
        self.hold()  # run as a background daemon

    def _capture_initial(self) -> bool:
        if self.monitor:
            self.monitor.capture_current()
        return False

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        action = None
        if "--action" in args:
            i = args.index("--action")
            if i + 1 < len(args):
                action = args[i + 1]
        if action == "history":
            self.show_history()
        elif action == "snippets":
            self.show_snippets()
        elif action == "menu":
            self.show_menu()
        elif action == "preferences":
            self.show_preferences()
        elif action == "quit":
            self.quit()
        # bare launch: the daemon is already up; nothing else to do.
        return 0

    # -- tray ------------------------------------------------------------
    def _setup_tray(self) -> None:
        try:
            conn = self.get_dbus_connection()
            if conn is None:
                conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.dbusmenu = DbusMenu(object_path="/org/clipy/Linux/MenuBar")
            self.sni = StatusNotifierItem(
                self.dbusmenu,
                item_id="clipy",
                title=APP_NAME,
                icon_name=self._tray_icon_name(),
                tooltip="Clipy — clipboard manager",
                object_path="/org/clipy/Linux/StatusNotifierItem",
                on_activate=self.show_history,
                on_secondary_activate=self.show_snippets,
            )
            self.sni.register(conn)
            self.rebuild_menu()
        except Exception as exc:  # tray is best-effort; app still works via hotkeys
            print(f"[clipy] tray setup failed: {exc}", file=sys.stderr)

    def _setup_injector(self) -> None:
        """Set up the RemoteDesktop-portal injector for Wayland-capable auto-paste."""
        self.injector = None
        if not (self.settings and self.settings.paste_after_select):
            return
        try:
            from .inject import PortalInjector
            conn = self.get_dbus_connection() or Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.injector = PortalInjector(conn)
            self.injector.start()  # prompts once, then silent via saved restore token
        except Exception as exc:
            print(f"[clipy] injector setup failed: {exc}", file=sys.stderr)

    def _tray_icon_name(self) -> str:
        """Use our packaged 'clipy' icon when installed; fall back to a themed icon."""
        try:
            display = Gdk.Display.get_default()
            if display is not None:
                theme = Gtk.IconTheme.get_for_display(display)
                if theme.has_icon("clipy"):
                    return "clipy"
        except Exception:
            pass
        return "edit-paste"

    def rebuild_menu(self) -> None:
        if not self.dbusmenu or not self.store or not self.settings:
            return
        s = self.settings
        children: list[MenuItem] = []

        # History section
        items = self.store.history(s.menu_history_count)
        start = 0 if s.number_from_zero else 1
        if items:
            children.append(MenuItem("History", enabled=False))
            for idx, item in enumerate(items):
                label = item.preview(s.max_menu_label_length)
                if s.add_numeric_keys and idx < 9:
                    label = f"{idx + start}. {label}"
                icon_name = None
                icon_data = None
                if item.kind == "image" and s.show_image_thumbnails and item.image_path:
                    icon_data = self._thumbnail(item.image_path)
                    if not icon_data and s.show_menu_icons:
                        icon_name = "image-x-generic"
                elif s.show_menu_icons:
                    icon_name = "image-x-generic" if item.kind == "image" else "text-x-generic"
                children.append(MenuItem(
                    label, icon_name=icon_name, icon_data=icon_data,
                    action=lambda it=item: self.select_history_item(it)))
        else:
            children.append(MenuItem("(No history)", enabled=False))
        children.append(MenuItem(separator=True))

        # Snippets section
        folders = self.store.folders()
        snippet_nodes: list[MenuItem] = []
        for folder in folders:
            if not folder.enabled:
                continue
            snips = [sn for sn in self.store.snippets(folder.id) if sn.enabled]
            if not snips:
                continue
            folder_children = [
                MenuItem(sn.title or "(untitled)",
                         action=lambda c=sn.content: self.paste_text(c))
                for sn in snips
            ]
            snippet_nodes.append(MenuItem(folder.name, children=folder_children))
        if snippet_nodes:
            if s.inline_snippets:
                children.append(MenuItem("Snippets", enabled=False))
                children.extend(snippet_nodes)
            else:
                children.append(MenuItem("Snippets", children=snippet_nodes))
            children.append(MenuItem(separator=True))

        # Actions
        if s.show_clear_history:
            children.append(MenuItem("Clear History…", action=self.clear_history))
        children.append(MenuItem("Edit Snippets…", action=self.show_snippets_manager))
        children.append(MenuItem("Preferences…", action=self.show_preferences))
        children.append(MenuItem(separator=True))
        children.append(MenuItem(f"Quit {APP_NAME}", action=self.quit))

        self.dbusmenu.set_root(MenuItem(children=children))

    def _thumbnail(self, path: str) -> bytes | None:
        """Small PNG thumbnail bytes for an image history item (menu icon-data)."""
        cache = getattr(self, "_thumb_cache", None)
        if cache is None:
            cache = self._thumb_cache = {}
        if path in cache:
            return cache[path]
        data = None
        try:
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 24, 24, True)
            ok, buf = pb.save_to_bufferv("png", [], [])
            if ok:
                data = bytes(buf)
        except Exception:
            data = None
        cache[path] = data
        return data

    def rebuild_menu_soon(self) -> None:
        """Debounced rebuild for rapid edits (e.g. typing a snippet)."""
        if self._rebuild_pending:
            return
        self._rebuild_pending = True

        def flush():
            self._rebuild_pending = False
            self.rebuild_menu()
            return False
        GLib.timeout_add(400, flush)

    # -- clipboard flow --------------------------------------------------
    def _on_capture(self, kind: str, text: str, image_bytes, is_secret: bool,
                    category: str = "text") -> None:
        if not self.store or not self.settings:
            return
        if is_secret and self.settings.ignore_password_managers:
            return
        if category not in self.settings.store_types:
            return
        if self._is_excluded():
            return
        added = None
        if kind == "text":
            added = self.store.add_text(text)
        elif kind == "image" and image_bytes is not None:
            added = self.store.add_image(image_bytes)
        if added is not None:
            self.store.trim_history(self.settings.max_history)
            self.rebuild_menu()
            self._refresh_open_history()

    def _is_excluded(self) -> bool:
        """True if the current source app is on the exclude list (best-effort)."""
        if not self.settings or not self.settings.exclude_apps:
            return False
        try:
            from . import x11
            app = x11.active_source_app()
        except Exception:
            app = None
        if not app:
            return False
        app_l = app.lower()
        return any(x.strip().lower() in app_l for x in self.settings.exclude_apps if x.strip())

    def select_history_item(self, item, paste: bool = True) -> None:
        if not self.monitor:
            return
        if item.kind == "image" and item.image_path:
            self.monitor.set_image_file(item.image_path)
        else:
            self.monitor.set_text(item.text)
        if self.settings and self.settings.reorder_after_paste:
            # Move the chosen entry to the top of the history (Clipy behaviour).
            self.store.touch_history(item.id)
            self.rebuild_menu()
        if paste and self.settings and self.settings.paste_after_select:
            self._try_paste()

    def paste_text(self, text: str, paste: bool = True) -> None:
        if self.monitor:
            self.monitor.set_text(text)
            if paste and self.settings and self.settings.paste_after_select:
                self._try_paste()

    def wants_auto_paste(self) -> bool:
        return bool(self.settings and self.settings.paste_after_select)

    def paste_now(self) -> bool:
        """Inject Ctrl+V once, immediately (no timer). Portal first (reaches native
        Wayland apps), XTEST fallback for X11/XWayland. Callers are responsible for
        having closed our popup and returned focus to the target app first."""
        try:
            if getattr(self, "injector", None) and self.injector.paste():
                return False
            from .paste import send_paste
            send_paste()
        except Exception:
            pass  # clipboard is set regardless; user can paste manually
        return False

    def _try_paste(self) -> None:
        """Auto-paste (Ctrl+V) into the target app after focus leaves our popup.

        Deferred slightly so the popup is gone and focus has returned to the app the
        user was in; otherwise the synthesised Ctrl+V would land on the popup. Used by
        the tray menu; the cursor menu drives paste_now() on a deterministic sequence.
        """
        GLib.timeout_add(140, self.paste_now)

    def clear_history(self) -> None:
        if not self.store:
            return
        if self.settings and self.settings.confirm_clear_history:
            self._confirm("Clear all clipboard history?", self._do_clear_history)
        else:
            self._do_clear_history()

    def _do_clear_history(self) -> None:
        self.store.clear_history()
        self.rebuild_menu()

    def _confirm(self, message: str, on_yes) -> None:
        """Modal yes/no confirmation (GTK4 AlertDialog)."""
        try:
            dialog = Gtk.AlertDialog()
            dialog.set_message(message)
            dialog.set_buttons(["Cancel", "OK"])
            dialog.set_default_button(1)
            dialog.set_cancel_button(0)

            def done(dlg, res):
                try:
                    if dlg.choose_finish(res) == 1:
                        on_yes()
                except GLib.Error:
                    pass
            dialog.choose(None, None, done)
        except Exception:
            on_yes()  # if the dialog API is unavailable, just proceed

    # -- windows ---------------------------------------------------------
    def _show_singleton(self, key: str, factory) -> Gtk.Window:
        win = self._windows.get(key)
        if win is None or not win.get_realized():
            win = factory()
            self._windows[key] = win
            win.connect("close-request", lambda *_: self._windows.pop(key, None) and False)
        win.present()
        return win

    def show_history(self) -> None:
        # Native menu at the mouse cursor (history + snippets + actions), like Clipy.
        self._show_cursor_menu("full")

    def show_menu(self) -> None:
        self._show_cursor_menu("full")

    def show_snippets(self) -> None:
        self._show_cursor_menu("snippets")

    def _show_cursor_menu(self, kind: str) -> None:
        from .ui.cursor_menu import CursorMenu
        old = self._windows.pop("cursor_menu", None)
        if old is not None:
            try:
                old._close()
            except Exception:
                pass
        menu = CursorMenu(self, kind)
        self._windows["cursor_menu"] = menu
        menu.show_at_cursor()

    def show_snippets_manager(self) -> None:
        self._show_singleton("snippets", lambda: SnippetWindow(self)).present()

    def show_preferences(self) -> None:
        self._show_singleton("preferences", lambda: PreferencesWindow(self)).present()

    def _refresh_open_history(self) -> None:
        return  # cursor menu is rebuilt each time it opens

    # -- settings side effects ------------------------------------------
    def apply_hotkeys(self) -> None:
        if not self.settings:
            return
        hotkeys.apply(self.settings.hotkeys, self._command_for)

    def _command_for(self, action: str) -> str:
        return f"{self.launcher_command} --action {action}"

    def set_autostart(self, enabled: bool) -> None:
        if enabled:
            AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART_PATH.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={APP_NAME}\n"
                f"Exec={self.launcher_command}\n"
                "X-GNOME-Autostart-enabled=true\n"
                "Terminal=false\n"
            )
        elif AUTOSTART_PATH.exists():
            AUTOSTART_PATH.unlink()
