"""Global hotkeys via GNOME custom keyboard shortcuts.

Wayland forbids apps from grabbing global keys, so we register entries under
``org.gnome.settings-daemon.plugins.media-keys`` that run ``clipy-linux --action X``.
The running instance receives the action over D-Bus. This also works on X11 sessions.
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
BASE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"

ACTIONS = ("history", "snippets", "menu")


def _schema_available() -> bool:
    source = Gio.SettingsSchemaSource.get_default()
    return bool(source and source.lookup(MEDIA_KEYS_SCHEMA, True)
                and source.lookup(CUSTOM_SCHEMA, True))


def _path_for(action: str) -> str:
    return f"{BASE_PATH}clipy-{action}/"


def apply(hotkeys: dict[str, str], command_for) -> bool:
    """Register/refresh Clipy's GNOME shortcuts.

    ``command_for(action)`` returns the shell command string to run for that action.
    Returns False if the GNOME schema is unavailable (e.g. non-GNOME desktop).
    """
    if not _schema_available():
        return False

    media = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
    current = list(media.get_strv("custom-keybindings"))

    for action in ACTIONS:
        path = _path_for(action)
        accel = (hotkeys.get(action) or "").strip()
        if accel:
            if path not in current:
                current.append(path)
            entry = Gio.Settings.new_with_path(CUSTOM_SCHEMA, path)
            entry.set_string("name", f"Clipy: show {action}")
            entry.set_string("command", command_for(action))
            entry.set_string("binding", accel)
        else:
            if path in current:
                current.remove(path)

    media.set_strv("custom-keybindings", current)
    Gio.Settings.sync()
    return True


def clear() -> None:
    """Remove all Clipy shortcuts (used on uninstall)."""
    if not _schema_available():
        return
    media = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
    current = [p for p in media.get_strv("custom-keybindings")
               if not p.startswith(f"{BASE_PATH}clipy-")]
    media.set_strv("custom-keybindings", current)
    Gio.Settings.sync()
