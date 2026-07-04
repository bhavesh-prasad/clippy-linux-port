"""XDG paths and user settings for Clipy.

Settings live in ``~/.config/clipy-linux/settings.json``; data (SQLite db, cached
images) lives under ``~/.local/share/clipy-linux/``. Defaults mirror Clipy's.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any


def _xdg(env: str, default: str) -> Path:
    value = os.environ.get(env)
    base = Path(value) if value else Path.home() / default
    return base


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "clipy-linux"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "clipy-linux"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
DB_PATH = DATA_DIR / "clipy.db"
IMAGE_CACHE_DIR = DATA_DIR / "images"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, IMAGE_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)


# Default hotkeys mirror Clipy's macOS defaults (⌘⇧V / ⌘⇧B), mapped to GNOME syntax.
# ⌘ maps to Ctrl on Linux; Ctrl+Shift+V does not clash with normal paste.
DEFAULT_HOTKEYS = {
    "history": "<Control><Shift>v",
    "snippets": "<Control><Shift>b",
    "menu": "<Control><Shift>c",
}

# Clipboard type categories we can distinguish on Linux, mapped from Clipy's types.
ALL_STORE_TYPES = ["text", "rich_text", "files", "image"]
STORE_TYPE_LABELS = {
    "text": "Plain text",
    "rich_text": "Rich text (HTML/RTF)",
    "files": "Files / paths",
    "image": "Images",
}


@dataclass
class Settings:
    # General
    max_history: int = 30
    store_types: list[str] = field(default_factory=lambda: list(ALL_STORE_TYPES))
    launch_at_login: bool = False
    # Menu
    menu_history_count: int = 20  # items shown inline in the tray menu
    max_menu_label_length: int = 40
    add_numeric_keys: bool = True  # 1..9 mnemonics on the first history items
    number_from_zero: bool = False  # start numbering at 0 instead of 1 (Clipy option)
    inline_snippets: bool = True
    show_menu_icons: bool = True  # type icon next to each history item
    show_image_thumbnails: bool = True  # thumbnail for image items in the menu
    show_clear_history: bool = True  # include the "Clear History" menu item
    # Behaviour
    paste_after_select: bool = True
    reorder_after_paste: bool = True  # move a selected item to the top after pasting
    confirm_clear_history: bool = True
    confirm_delete_snippet: bool = True
    exclude_apps: list[str] = field(default_factory=list)
    ignore_password_managers: bool = True  # skip entries flagged x-kde-passwordManagerHint
    # Hotkeys (GNOME accelerator strings)
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(SETTINGS_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        data: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
        merged = cls()
        for k, v in data.items():
            setattr(merged, k, v)
        # Ensure all hotkey slots exist.
        for k, v in DEFAULT_HOTKEYS.items():
            merged.hotkeys.setdefault(k, v)
        return merged

    def save(self) -> None:
        ensure_dirs()
        tmp = SETTINGS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(SETTINGS_PATH)
