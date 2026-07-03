# Clipy for Linux — Design

A faithful clone of [Clipy](https://github.com/Clipy/Clipy) (macOS menu-bar clipboard
manager) for Ubuntu/Linux, targeting GNOME on Wayland out of the box while degrading
gracefully to X11 and other desktops.

## Goal

Reproduce Clipy's core experience on Linux:

- A **tray/menu-bar icon** that is the entire app (no persistent main window).
- **Clipboard history**: records copied text and images, shown in the tray menu and a
  searchable popup window, with a configurable maximum count.
- **Snippets**: reusable text organized into folders, with a manager/editor window and a
  snippets submenu in the tray.
- **Global hotkeys**: pop the history menu, snippets menu, and main menu from anywhere.
- **Preferences**: history size, stored types, hotkeys, launch-at-login, exclusions.
- **Persistence** across restarts.

## Key constraints discovered on the target machine

- Ubuntu 24.04, **Wayland + GNOME**, Python 3.12.
- **No `pip`, no PySide6/PyQt, no AppIndicator lib, no `wl-clipboard`/`xclip`.**
- **`sudo` requires a password** → cannot install system packages unattended.
- **Available with zero installs**: PyGObject 3.48 (GTK3 **and** GTK4), Gio/GLib D-Bus,
  `sqlite3` (stdlib), `gsettings`.
- `org.kde.StatusNotifierWatcher` is running with a host registered (Ubuntu's
  AppIndicator GNOME extensions) → a StatusNotifierItem we publish over D-Bus **will**
  appear in the top bar.

## Stack decision

**Python 3 + PyGObject (GTK4) + Gio D-Bus.** Chosen over Qt/Electron/Rust because it is
the only stack that needs **zero installation** on the target machine, is the most native
to GNOME, and iterates fastest for a faithful clone. Trade-off: we hand-roll the tray
(SNI + dbusmenu) instead of using AppIndicator, which is more code but removes the only
system dependency.

## Architecture

Single long-running process owning a well-known D-Bus name (single instance). CLI
invocations of the same binary become lightweight D-Bus clients that ask the running
instance to perform an action (show a menu/window) — this is also how Wayland global
hotkeys reach the app.

```
clipy/
  __main__.py        entry: parse CLI action, single-instance via D-Bus name ownership
  app.py             ClipyApplication (Gio.Application) — wires all components
  config.py          XDG paths + settings (JSON in ~/.config/clipy-linux/)
  models.py          HistoryItem, Snippet, SnippetFolder dataclasses
  storage.py         SQLite: history store + snippet store
  clipboard.py       ClipboardMonitor over Gdk clipboard (text + image), dedupe
  ipc.py             D-Bus service org.clipy.Linux: ShowHistory/ShowSnippets/ShowMenu/...
  hotkeys.py         register/unregister GNOME custom shortcuts via gsettings
  icons.py           tray icon (themed name + bundled PNG fallback)
  sni/
    item.py          org.kde.StatusNotifierItem D-Bus object
    dbusmenu.py      com.canonical.dbusmenu D-Bus object (menu model + events)
    menu_model.py    in-memory menu tree the tray renders (history/snippets/actions)
  ui/
    history_window.py     searchable history list popup (hotkey target)
    snippet_window.py     snippet folders/items manager + editor
    preferences_window.py tabbed preferences (General/Menu/Type/Shortcuts)
bin/clipy-linux      launcher shell script
data/                icons, .desktop file
README.md
```

## Data flow

1. `ClipboardMonitor` observes the Gdk clipboard's `changed` signal; on change reads the
   available content (prefer image, else text), skips if identical to the newest history
   item or if the source app is excluded, and inserts a `HistoryItem` into SQLite.
2. On insert it trims history to the configured max and asks the SNI menu model to
   rebuild its "history" section; the tray menu reflects it immediately.
3. Selecting a history item (tray menu, or the popup window) writes it back to the Gdk
   clipboard and optionally triggers paste.
4. Snippets live in SQLite; the snippet manager edits them and rebuilds the snippets
   submenu.
5. Global hotkeys are GNOME custom shortcuts bound to `clipy-linux --action history`
   (etc.). That invocation sends a D-Bus method to the running instance, which shows the
   relevant menu/window.

## Tray (SNI + dbusmenu)

We implement two D-Bus objects with Gio:

- `org.kde.StatusNotifierItem` at `/StatusNotifierItem` — exposes icon, tooltip, and a
  `Menu` object path; registers itself with `org.kde.StatusNotifierWatcher`.
- `com.canonical.dbusmenu` at `/MenuBar` — serves the menu layout (`GetLayout`), item
  properties, and receives `Event` (clicks). GNOME's AppIndicator extension renders
  left-click as this menu.

`menu_model.py` holds the tree: History section (recent items, truncated labels),
Snippets submenu (folders → items), then Clear History / Snippets… / Preferences… /
Quit. Rebuilds emit `LayoutUpdated` so the extension refreshes.

## Clipboard access without CLI tools — and the Wayland focus problem

GTK reads/writes the clipboard directly via `Gdk.Display.get_clipboard()` (text with
`read_text_async`, images with `read_texture_async` → PNG bytes), so no
`wl-clipboard`/`xclip` is needed.

**Critical constraint:** on GNOME Wayland (Mutter 46) a background app **cannot** read
the clipboard — native `wl_data_device` access requires keyboard focus, and Mutter
exposes **no** `wlr-data-control`/`ext-data-control` protocol for clipboard managers
(verified on the target machine). A tray app never has focus, so pure-Wayland monitoring
is impossible here.

**Solution (verified):** run the app under **XWayland** by forcing `GDK_BACKEND=x11`.
X11 clients read the `CLIPBOARD` selection without focus (XFixes selection-notify), and
Mutter **bridges** native Wayland copies into the XWayland selection. Tested end to end:
both X11→X11 and Wayland-copy→X11-read captured with no focus. The D-Bus tray and
gsettings hotkeys are display-agnostic, so forcing x11 costs nothing. The launcher and
`__main__` set `GDK_BACKEND=x11` (overridable). On a native X11 session this is a no-op.

## Global hotkeys on Wayland

Wayland forbids apps from grabbing global keys, so we register **GNOME custom keyboard
shortcuts** through `gsettings`
(`org.gnome.settings-daemon.plugins.media-keys custom-keybindings`) that run
`clipy-linux --action {history,snippets,menu}`. Defaults mirror Clipy:
- History: `<Control><Alt>v`  · Snippets: `<Control><Alt>b`  · Menu: `<Control><Alt>c`
(configurable in Preferences). On X11 this same mechanism works; a future enhancement can
add a direct X11 grab. Because Wayland cannot position a popup under the pointer, the
hotkey opens a **centered searchable popup window** (an improvement over a blind menu).

## Persistence

`~/.config/clipy-linux/settings.json` for preferences; `~/.local/share/clipy-linux/
clipy.db` (SQLite) for history and snippets. History table: id, kind(text|image), text,
image_path/blob, source_app, hash, created_at. Snippets: folders(id,name,ordering,
enabled) and snippets(id,folder_id,title,content,ordering,enabled).

## Error handling

- D-Bus registration failures (no watcher) → log, keep running headless, retry on
  watcher appearing (`NameOwnerChanged`).
- Clipboard read errors → ignored per-event, never crash the monitor.
- Excluded/empty content → skipped silently.
- Second instance → forwards its `--action` over D-Bus and exits 0.

## Testing / verification

- Unit-testable core: storage (CRUD + trim + dedupe), menu_model rendering, config.
- Integration: launch process → assert our name owns the bus, SNI registered with the
  watcher, a simulated clipboard change produces a history row, menu `GetLayout` returns
  expected items.

## Scope (v1)

In: history (text+image), snippets + manager, tray menu, searchable popup, preferences
(general/menu/shortcuts), hotkeys via gsettings, launch-at-login, persistence, quit.
Deferred: per-app exclusion UI polish, rich-text fidelity, thumbnails in menu, sound,
auto-update, X11 direct key grab.

## Non-goals

Pixel-identical macOS chrome (we use native GTK). Behavioral and feature parity is the
target, not visual mimicry of Aqua.
