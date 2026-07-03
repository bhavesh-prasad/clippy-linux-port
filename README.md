# Clipy for Linux

A faithful Linux clone of [Clipy](https://github.com/Clipy/Clipy), the macOS menu-bar
clipboard manager. It lives in your system tray and gives you clipboard **history** and
reusable **snippets**, reachable from the tray menu, global hotkeys, and searchable
pop-up windows.

Built with **Python 3 + GTK4 (PyGObject)** and D-Bus. On Ubuntu 24.04 / GNOME it needs
**no extra packages** — no `pip install`, no `apt install`, no root.

## Features

- **Clipboard history** — text and images, with a configurable maximum count. Duplicates
  are de-duplicated and re-copying an old entry moves it to the top (like Clipy).
- **Snippets** — reusable text organised into folders, with a manager/editor window and a
  snippets submenu in the tray.
- **Tray icon** — the whole app lives in the GNOME top bar (StatusNotifierItem). Left-click
  opens the menu; the menu holds recent history, snippets, and actions.
- **Global hotkeys** — pop the history, snippets, or menu from anywhere.
- **Searchable pop-ups** — type to filter, arrow keys to move, Enter to paste, `1`–`9` for
  quick pick, `Delete` to remove a history entry, `Esc` to close.
- **Preferences** — history size, stored types, menu options, hotkeys, launch-at-login.
- **Persistence** — history and snippets stored in SQLite under `~/.local/share/clipy-linux/`.

## Requirements

Already present on a standard Ubuntu 24.04 GNOME install:

- Python 3.10+
- PyGObject with GTK 4 (`python3-gi`, `gir1.2-gtk-4.0`) — preinstalled on Ubuntu GNOME
- A StatusNotifier host — Ubuntu's AppIndicator GNOME extension, enabled by default

Optional, only for **auto-paste after selecting** (otherwise the entry is placed on the
clipboard and you press Ctrl+V yourself): `ydotool` (Wayland) or `python3-xlib` (X11).

## Run

```bash
./bin/clipy-linux
```

That starts the background daemon and puts the clipboard icon in your top bar. Run it
again with an action to drive the running instance (this is what the hotkeys do):

```bash
./bin/clipy-linux --action history      # searchable history pop-up
./bin/clipy-linux --action snippets     # snippet picker
./bin/clipy-linux --action menu         # main menu (history pop-up)
./bin/clipy-linux --action preferences  # preferences
./bin/clipy-linux --action quit         # stop the daemon
```

### The Wayland clipboard note (important)

GNOME Wayland does **not** let a background app read the clipboard (Mutter exposes no
`data-control` protocol, and normal clipboard access requires window focus). Clipy for
Linux therefore runs under **XWayland** (`GDK_BACKEND=x11`, set automatically by the
launcher). Mutter bridges native Wayland copies into the X11 clipboard, so history capture
works without focus. On a native X11 session this is a no-op. You do not need to change
anything — just run the launcher.

## Global hotkeys

The app registers GNOME custom keyboard shortcuts (via `gsettings`) that invoke
`clipy-linux --action …`. Defaults mirror Clipy:

| Action   | Default shortcut     |
|----------|----------------------|
| History  | `Ctrl+Alt+V`         |
| Snippets | `Ctrl+Alt+B`         |
| Menu     | `Ctrl+Alt+C`         |

Change them in **Preferences → Shortcuts** (GNOME accelerator syntax, e.g.
`<Control><Alt>v`). They appear under **Settings → Keyboard → Custom Shortcuts**.

## Start automatically at login

Toggle **Preferences → General → Launch at login**, or run once and enable it. This writes
`~/.config/autostart/clipy-linux.desktop`.

## Install (optional)

To run it as `clipy-linux` from anywhere:

```bash
ln -s "$(pwd)/bin/clipy-linux" ~/.local/bin/clipy-linux   # ensure ~/.local/bin is on PATH
```

A desktop launcher for the app grid is in `data/clipy-linux.desktop` — copy it to
`~/.local/share/applications/` and fix its `Exec=`/`Icon=` paths.

## Uninstall / reset

```bash
./bin/clipy-linux --action quit                 # stop the daemon
python3 -c "from clipy import hotkeys; hotkeys.clear()"   # remove GNOME shortcuts
rm -f ~/.config/autostart/clipy-linux.desktop   # disable autostart
rm -rf ~/.local/share/clipy-linux ~/.config/clipy-linux   # data + settings
```

## Architecture

See [`docs/superpowers/specs/2026-07-03-clipy-linux-design.md`](docs/superpowers/specs/2026-07-03-clipy-linux-design.md)
for the full design. In brief:

```
clipy/
  __main__.py     entry point (forces XWayland backend)
  app.py          ClipyApplication — wires everything, single-instance + --action IPC
  config.py       settings (JSON) + XDG paths
  models.py       HistoryItem / Snippet / SnippetFolder
  storage.py      SQLite history + snippet store
  clipboard.py    ClipboardMonitor over GDK (text + image), focus-free via XWayland
  hotkeys.py      GNOME custom shortcuts via gsettings
  paste.py        best-effort auto-paste (ydotool / XTEST)
  sni/            hand-rolled StatusNotifierItem + com.canonical.dbusmenu (Gio D-Bus)
  ui/             history pop-up, snippet manager + picker, preferences
```

The tray is implemented directly against the `org.kde.StatusNotifierItem` and
`com.canonical.dbusmenu` D-Bus interfaces, so it needs no `libappindicator`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Not (yet) a pixel copy

This clone matches Clipy's **behaviour and features** using native GTK widgets; it does not
mimic macOS Aqua chrome. Deferred: per-app exclusion UI, rich-text fidelity, in-menu image
thumbnails, sound, and auto-update.
