"""A ``org.kde.StatusNotifierItem`` published over Gio D-Bus.

Registers with ``org.kde.StatusNotifierWatcher`` so the desktop shows a tray icon whose
left-click opens our :class:`~clipy.sni.dbusmenu.DbusMenu`.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .dbusmenu import DbusMenu

SNI_IFACE = "org.kde.StatusNotifierItem"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"

INTROSPECTION_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Activate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Scroll">
      <arg type="i" name="delta" direction="in"/>
      <arg type="s" name="orientation" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg type="s" name="status"/>
    </signal>
  </interface>
</node>
"""


class StatusNotifierItem:
    def __init__(
        self,
        menu: DbusMenu,
        *,
        item_id: str = "clipy",
        title: str = "Clipy",
        icon_name: str = "edit-paste",
        tooltip: str = "Clipy — clipboard manager",
        on_activate: Callable[[], None] | None = None,
        on_secondary_activate: Callable[[], None] | None = None,
        object_path: str = "/StatusNotifierItem",
    ):
        self.menu = menu
        self.item_id = item_id
        self.title = title
        self.icon_name = icon_name
        self.tooltip = tooltip
        self.on_activate = on_activate
        self.on_secondary_activate = on_secondary_activate
        self.object_path = object_path
        self._conn: Gio.DBusConnection | None = None
        self._reg_id: int | None = None
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)

    def register(self, conn: Gio.DBusConnection) -> None:
        self._conn = conn
        self._reg_id = conn.register_object(
            self.object_path,
            self._node_info.interfaces[0],
            self._on_method_call,
            self._on_get_property,
            None,
        )
        self.menu.register(conn)
        self._register_with_watcher()
        # If the watcher restarts (e.g. extension toggled), re-register.
        Gio.bus_watch_name_on_connection(
            conn, WATCHER_NAME, Gio.BusNameWatcherFlags.NONE,
            lambda *a: self._register_with_watcher(), None)

    def _register_with_watcher(self) -> None:
        if not self._conn:
            return
        # Register by OBJECT PATH, not bus name. The watcher then derives the sender and
        # records "<busname>@<path>", so our item is found even at a non-standard path.
        # Passing the bus name instead makes hosts look at /StatusNotifierItem and miss us.
        service = self.object_path
        self._conn.call(
            WATCHER_NAME, WATCHER_PATH, WATCHER_NAME,
            "RegisterStatusNotifierItem", GLib.Variant("(s)", (service,)),
            None, Gio.DBusCallFlags.NONE, -1, None,
            lambda src, res: self._finish_register(src, res))

    def _finish_register(self, src, res) -> None:
        try:
            src.call_finish(res)
        except GLib.Error as exc:
            # No watcher yet, or it rejected us; the name-watch retries when it appears.
            print(f"[clipy] StatusNotifierItem registration failed: {exc}",
                  file=__import__("sys").stderr)

    def set_icon(self, icon_name: str) -> None:
        self.icon_name = icon_name
        if self._conn:
            self._conn.emit_signal(None, self.object_path, SNI_IFACE, "NewIcon", None)

    def set_tooltip(self, text: str) -> None:
        self.tooltip = text
        if self._conn:
            self._conn.emit_signal(None, self.object_path, SNI_IFACE, "NewToolTip", None)

    # -- D-Bus handlers --------------------------------------------------
    def _on_get_property(self, conn, sender, path, iface, name):
        props = {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", self.item_id),
            "Title": ("s", self.title),
            "Status": ("s", "Active"),
            "WindowId": ("i", 0),
            "IconName": ("s", self.icon_name),
            "IconThemePath": ("s", ""),
            "OverlayIconName": ("s", ""),
            "AttentionIconName": ("s", ""),
            "AttentionMovieName": ("s", ""),
            "ItemIsMenu": ("b", True),
            "Menu": ("o", self.menu.object_path),
        }
        if name in props:
            sig, val = props[name]
            return GLib.Variant(sig, val)
        if name == "IconPixmap":
            return GLib.Variant("a(iiay)", [])
        if name == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", ("", [], self.title, self.tooltip))
        return None

    def _on_method_call(self, conn, sender, path, iface, method, params, invocation):
        if method in ("Activate",):
            if self.on_activate:
                GLib.idle_add(lambda: (self.on_activate(), False)[1])
            invocation.return_value(None)
        elif method == "SecondaryActivate":
            if self.on_secondary_activate:
                GLib.idle_add(lambda: (self.on_secondary_activate(), False)[1])
            invocation.return_value(None)
        elif method in ("ContextMenu", "Scroll"):
            invocation.return_value(None)
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method)
