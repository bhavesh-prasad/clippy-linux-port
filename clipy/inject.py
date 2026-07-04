"""Keyboard injection via the XDG RemoteDesktop portal.

This is the only way to synthesise input that reaches **native Wayland** apps on GNOME
without root (XTEST only reaches XWayland/X11 windows). We create one persistent portal
session at startup; GNOME shows an "allow remote control" dialog the first time, then a
saved restore-token keeps it silent on future runs.

Everything is best-effort: if the portal is missing or the user declines, ``paste()``
just does nothing and the content is left on the clipboard for a manual Ctrl+V.
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import config

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
RD_IFACE = "org.freedesktop.portal.RemoteDesktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"

# evdev key codes (linux/input-event-codes.h)
KEY_LEFTCTRL = 29
KEY_V = 47

TOKEN_PATH = config.CONFIG_DIR / "portal_restore_token"


class PortalInjector:
    def __init__(self, connection: Gio.DBusConnection):
        self.bus = connection
        self.session_handle: str | None = None
        self.ready = False
        self._starting = False
        self._token_counter = 0

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Begin the portal handshake. Safe to call once at startup."""
        if self.ready or self._starting or self.bus is None:
            return
        self._starting = True
        self._create_session()

    def _new_token(self) -> str:
        self._token_counter += 1
        return f"clipy{self._token_counter}"

    def _load_restore_token(self) -> str:
        try:
            return TOKEN_PATH.read_text().strip()
        except OSError:
            return ""

    def _save_restore_token(self, token: str) -> None:
        if not token:
            return
        try:
            config.ensure_dirs()
            TOKEN_PATH.write_text(token)
        except OSError:
            pass

    # -- portal request/response plumbing --------------------------------
    def _request(self, method: str, params: GLib.Variant, on_response) -> None:
        try:
            reply = self.bus.call_sync(
                PORTAL, PORTAL_PATH, RD_IFACE, method, params,
                GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error:
            self._starting = False
            return
        req_path = reply.unpack()[0]
        sub = [0]

        def handler(conn, sender, path, iface, signal, p):
            self.bus.signal_unsubscribe(sub[0])
            code, results = p.unpack()
            on_response(code, results)
        sub[0] = self.bus.signal_subscribe(
            PORTAL, REQUEST_IFACE, "Response", req_path, None,
            Gio.DBusSignalFlags.NONE, handler)

    def _create_session(self) -> None:
        opts = {
            "handle_token": GLib.Variant("s", self._new_token()),
            "session_handle_token": GLib.Variant("s", "clipy"),
        }
        self._request("CreateSession", GLib.Variant("(a{sv})", (opts,)), self._on_created)

    def _on_created(self, code: int, results: dict) -> None:
        if code != 0 or "session_handle" not in results:
            self._starting = False
            return
        self.session_handle = results["session_handle"]
        opts = {
            "handle_token": GLib.Variant("s", self._new_token()),
            "types": GLib.Variant("u", 1),          # 1 = KEYBOARD
            "persist_mode": GLib.Variant("u", 2),   # 2 = persist until revoked
        }
        token = self._load_restore_token()
        if token:
            opts["restore_token"] = GLib.Variant("s", token)
        self._request("SelectDevices",
                      GLib.Variant("(oa{sv})", (self.session_handle, opts)),
                      self._on_selected)

    def _on_selected(self, code: int, results: dict) -> None:
        if code != 0:
            self._starting = False
            return
        opts = {"handle_token": GLib.Variant("s", self._new_token())}
        self._request("Start",
                      GLib.Variant("(osa{sv})", (self.session_handle, "", opts)),
                      self._on_started)

    def _on_started(self, code: int, results: dict) -> None:
        self._starting = False
        if code != 0:
            self.session_handle = None
            return
        if "restore_token" in results:
            self._save_restore_token(results["restore_token"])
        self.ready = True

    # -- pasting ---------------------------------------------------------
    def paste(self) -> bool:
        """Inject Ctrl+V into the focused window. Returns True if sent."""
        if not self.ready or not self.session_handle or self.bus is None:
            if not self.ready:
                self.start()  # kick off setup for next time
            return False
        try:
            for keycode, state in ((KEY_LEFTCTRL, 1), (KEY_V, 1), (KEY_V, 0),
                                   (KEY_LEFTCTRL, 0)):
                self.bus.call_sync(
                    PORTAL, PORTAL_PATH, RD_IFACE, "NotifyKeyboardKeycode",
                    GLib.Variant("(oa{sv}iu)", (self.session_handle, {}, keycode, state)),
                    None, Gio.DBusCallFlags.NONE, -1, None)
            return True
        except GLib.Error:
            # Session died (e.g. revoked); reset so we re-establish next time.
            self.ready = False
            self.session_handle = None
            return False
