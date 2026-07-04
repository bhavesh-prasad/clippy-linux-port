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
- **Compact popup at the cursor** — the history/snippets hotkey opens a small Clipy-style
  chooser right where your mouse is; type to filter, Enter to paste, `1`–`9` quick-pick.
- **Global hotkeys** — History `Ctrl+Shift+V`, Snippets `Ctrl+Shift+B`, Menu `Ctrl+Shift+C`.
- **Type filters** — choose which categories to record: plain text, rich text, files, images.
- **Menu options** — image thumbnails, numeric keys (from 0 or 1), type icons, show/hide
  Clear History, reorder-after-paste, inline vs. foldered snippets.
- **Confirmations** — optional confirm before clearing history or deleting a snippet.
- **Exclude apps** — skip recording from chosen apps (by window class; X11/XWayland apps).
- **Preferences** — General, Menu, Type, Shortcuts, Applications tabs; launch-at-login.
- **Persistence** — history and snippets stored in SQLite under `~/.local/share/clipy-linux/`.

## Requirements

Already present on a standard Ubuntu 24.04 GNOME install:

- Python 3.10+
- PyGObject with GTK 4 (`python3-gi`, `gir1.2-gtk-4.0`) — preinstalled on Ubuntu GNOME
- A StatusNotifier host — Ubuntu's AppIndicator GNOME extension, enabled by default

**Auto-paste after selecting**: choosing an entry places it on the clipboard and pastes
(Ctrl+V) into the app you were in. To reach **native Wayland** apps this uses the XDG
**RemoteDesktop portal**, so GNOME shows an "allow remote control" prompt the **first
time** — approve it once and a saved restore-token keeps it silent afterwards. (XTEST via
`libX11`/`libXtst` is used as a fallback for X11/XWayland targets.) Turn it off in
**Preferences → General → "Paste automatically after selecting"**.

## Install (.deb package)

Build the package (no root, no extra tooling needed — just `dpkg-deb`, which ships with
Debian/Ubuntu):

```bash
packaging/build-deb.sh          # produces dist/clipy_0.1.0_all.deb
```

Install it — double-click it in the Software app, or:

```bash
sudo apt install ./dist/clipy_0.1.0_all.deb
```

`apt` pulls in the dependencies (`python3-gi`, `gir1.2-gtk-4.0`, …; all preinstalled on
Ubuntu GNOME) and adds a **Clipy** entry to your app grid plus a `clipy` command. Launch
it from the app grid or run `clipy`. Uninstall with:

```bash
sudo apt remove clipy
```

(This leaves your history/settings and GNOME shortcuts in place; see **Uninstall / reset**
below to remove those too.)

## Run

Once installed, start it from the app grid or:

```bash
clipy
```

That starts the background daemon and puts the clipboard icon in your top bar. Run it
again with an action to drive the running instance (this is what the hotkeys do):

```bash
clipy --action history      # searchable history pop-up
clipy --action snippets     # snippet picker
clipy --action menu         # main menu (history pop-up)
clipy --action preferences  # preferences
clipy --action quit         # stop the daemon
```

### Run from source (without installing)

```bash
./bin/clipy-linux            # same commands, add --action … as above
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
`clipy-linux --action …`. Defaults mirror Clipy's macOS combos (⌘→Ctrl):

| Action   | Default shortcut     | Clipy (macOS) |
|----------|----------------------|---------------|
| History  | `Ctrl+Shift+V`       | ⌘⇧V           |
| Snippets | `Ctrl+Shift+B`       | ⌘⇧B           |
| Menu     | `Ctrl+Shift+C`       | —             |

Pressing the history/snippets shortcut opens a **compact popup at the mouse cursor**
(Clipy-style): type to filter, ↑/↓ to move, Enter to paste, `1`–`9` to quick-pick,
`Delete` to remove a history entry, `Esc` to close. Change the bindings in
**Preferences → Shortcuts** (GNOME accelerator syntax, e.g. `<Control><Shift>v`); they
also appear under **Settings → Keyboard → Custom Shortcuts**.

## Start automatically at login

Toggle **Preferences → General → Launch at login**, or run once and enable it. This writes
`~/.config/autostart/clipy-linux.desktop`.

## Uninstall / reset

```bash
clipy --action quit                             # stop the daemon
sudo apt remove clipy                           # remove the package (if installed via .deb)
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
