"""A minimal ``com.canonical.dbusmenu`` server object.

The tray host (GNOME's AppIndicator extension) calls ``GetLayout`` to render the menu
and ``Event`` when the user clicks. We keep an in-memory tree of :class:`MenuItem`
nodes; :meth:`DbusMenu.set_root` swaps the tree and bumps the revision so the host
re-fetches the layout.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

DBUSMENU_IFACE = "com.canonical.dbusmenu"

INTROSPECTION_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg type="i" name="id"/>
      <arg type="u" name="timestamp"/>
    </signal>
  </interface>
</node>
"""


class MenuItem:
    """A node in the tray menu tree.

    ``action`` is invoked when the item is clicked. Set ``children`` for submenus and
    ``separator=True`` for a divider.
    """

    def __init__(
        self,
        label: str = "",
        *,
        action: Callable[[], None] | None = None,
        enabled: bool = True,
        visible: bool = True,
        icon_name: str | None = None,
        separator: bool = False,
        toggle_type: str = "",       # "" | "checkmark" | "radio"
        toggle_state: int = -1,      # -1 none, 0 off, 1 on
        children: list["MenuItem"] | None = None,
    ):
        self.label = label
        self.action = action
        self.enabled = enabled
        self.visible = visible
        self.icon_name = icon_name
        self.separator = separator
        self.toggle_type = toggle_type
        self.toggle_state = toggle_state
        self.children = children or []
        self.id = 0  # assigned during (re)build

    def properties(self, names: list[str] | None = None) -> dict[str, GLib.Variant]:
        props: dict[str, GLib.Variant] = {}
        if self.separator:
            props["type"] = GLib.Variant("s", "separator")
        if self.label:
            props["label"] = GLib.Variant("s", self.label)
        if not self.enabled:
            props["enabled"] = GLib.Variant("b", False)
        if not self.visible:
            props["visible"] = GLib.Variant("b", False)
        if self.icon_name:
            props["icon-name"] = GLib.Variant("s", self.icon_name)
        if self.children:
            props["children-display"] = GLib.Variant("s", "submenu")
        if self.toggle_type:
            props["toggle-type"] = GLib.Variant("s", self.toggle_type)
        if self.toggle_state >= 0:
            props["toggle-state"] = GLib.Variant("i", self.toggle_state)
        if names:
            props = {k: v for k, v in props.items() if k in names}
        return props


class DbusMenu:
    def __init__(self, object_path: str = "/MenuBar"):
        self.object_path = object_path
        self.root = MenuItem()
        self.root.id = 0
        self._by_id: dict[int, MenuItem] = {0: self.root}
        self.revision = 1
        self._reg_id: int | None = None
        self._conn: Gio.DBusConnection | None = None
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)

    # -- lifecycle -------------------------------------------------------
    def register(self, conn: Gio.DBusConnection) -> None:
        self._conn = conn
        self._reg_id = conn.register_object(
            self.object_path,
            self._node_info.interfaces[0],
            self._on_method_call,
            self._on_get_property,
            None,
        )

    def unregister(self) -> None:
        if self._conn and self._reg_id:
            self._conn.unregister_object(self._reg_id)
            self._reg_id = None

    # -- tree management -------------------------------------------------
    def set_root(self, root: MenuItem) -> None:
        """Replace the menu tree and notify the host to re-fetch it."""
        self.root = root
        self.root.id = 0
        self._reindex()
        self.revision += 1
        self._emit_layout_updated()

    def _reindex(self) -> None:
        self._by_id = {0: self.root}
        counter = [1]

        def walk(item: MenuItem) -> None:
            for child in item.children:
                child.id = counter[0]
                counter[0] += 1
                self._by_id[child.id] = child
                walk(child)

        walk(self.root)

    def _emit_layout_updated(self) -> None:
        if not self._conn:
            return
        self._conn.emit_signal(
            None, self.object_path, DBUSMENU_IFACE, "LayoutUpdated",
            GLib.Variant("(ui)", (self.revision, 0)),
        )

    # -- serialization ---------------------------------------------------
    def _serialize(self, item: MenuItem, depth: int, names: list[str] | None):
        """Return a native ``(id, props, av)`` tuple for the ``(ia{sv}av)`` type.

        Children are wrapped in ``v`` variants (the ``av`` array element type); the
        node itself stays a native tuple so it can be embedded either directly (the
        GetLayout return) or inside a ``v`` (as a child).
        """
        props = item.properties(names)
        children: list[GLib.Variant] = []
        if depth != 0:
            next_depth = -1 if depth < 0 else depth - 1
            for child in item.children:
                if not child.visible:
                    continue
                child_tuple = self._serialize(child, next_depth, names)
                children.append(
                    GLib.Variant("v", GLib.Variant("(ia{sv}av)", child_tuple)))
        return (item.id, props, children)

    # -- D-Bus handlers --------------------------------------------------
    def _on_get_property(self, conn, sender, path, iface, name):
        if name == "Version":
            return GLib.Variant("u", 3)
        if name == "Status":
            return GLib.Variant("s", "normal")
        if name == "TextDirection":
            return GLib.Variant("s", "ltr")
        if name == "IconThemePath":
            return GLib.Variant("as", [])
        return None

    def _on_method_call(self, conn, sender, path, iface, method, params, invocation):
        try:
            if method == "GetLayout":
                parent_id, depth, names = params.unpack()
                names = list(names) or None
                root = self._by_id.get(parent_id, self.root)
                layout = self._serialize(root, depth, names)
                invocation.return_value(GLib.Variant("(u(ia{sv}av))",
                                                     (self.revision, layout)))
            elif method == "GetGroupProperties":
                ids, names = params.unpack()
                names = list(names) or None
                out = []
                targets = ids if ids else list(self._by_id)
                for i in targets:
                    item = self._by_id.get(i)
                    if item is not None:
                        out.append((i, item.properties(names)))
                invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
            elif method == "GetProperty":
                item_id, name = params.unpack()
                item = self._by_id.get(item_id)
                val = item.properties([name]).get(name) if item else None
                if val is None:
                    val = GLib.Variant("s", "")
                invocation.return_value(GLib.Variant("(v)", (val,)))
            elif method == "Event":
                item_id, event_id, _data, _ts = params.unpack()
                if event_id == "clicked":
                    self._activate(item_id)
                invocation.return_value(None)
            elif method == "EventGroup":
                events, = params.unpack()
                for item_id, event_id, _data, _ts in events:
                    if event_id == "clicked":
                        self._activate(item_id)
                invocation.return_value(GLib.Variant("(ai)", ([],)))
            elif method == "AboutToShow":
                invocation.return_value(GLib.Variant("(b)", (False,)))
            elif method == "AboutToShowGroup":
                invocation.return_value(GLib.Variant("(aiai)", ([], [])))
            else:
                invocation.return_error_literal(
                    Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method)
        except Exception as exc:  # never let a handler kill the bus connection
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.FAILED, str(exc))

    def _activate(self, item_id: int) -> None:
        item = self._by_id.get(item_id)
        if item and item.action and item.enabled:
            # Defer to the main loop so we return from the D-Bus call promptly.
            GLib.idle_add(lambda: (item.action(), False)[1])
