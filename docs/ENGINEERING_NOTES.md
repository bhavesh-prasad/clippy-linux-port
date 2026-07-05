# Clipy for Linux — Engineering Notes & Decision Log

This document is the *why* behind the port: every hard problem, the reasoning that led to
each decision, the dead ends, and how each fix was verified. It is deliberately exhaustive —
if you want the short user-facing version, read [`README.md`](../README.md) instead.

The goal was a **faithful Linux clone of the macOS [Clipy](https://github.com/Clipy/Clipy)**:
a menu-bar clipboard manager with clipboard history, reusable snippets organised in folders,
a tray icon, global hotkeys, a menu that pops at the mouse cursor, auto-paste on select, and
preferences — with *no visible difference* in behaviour from the original.

---

## 1. The core constraint: macOS gives you things Linux/Wayland does not

Clipy on macOS leans on three OS capabilities that "just work" there and are each a fight on
Linux, especially **GNOME Wayland** (the modern Ubuntu default):

| Capability | macOS (Clipy) | GNOME Wayland (this port) |
|---|---|---|
| Read the clipboard in the background | `NSPasteboard` polling, always allowed | Wayland forbids background clipboard reads entirely |
| A menu-bar/status item | `NSStatusItem`, first-class API | No native API; must hand-roll the `StatusNotifierItem` D-Bus protocol |
| Synthesise ⌘V / Ctrl+V into another app | `CGEvent` + **Accessibility permission** | Wayland forbids cross-app input injection; needs the RemoteDesktop **portal** |

Two extra environment constraints shaped everything:

- **No root, no `pip`, no `apt`** were available for development. So the whole app had to be
  built from what ships on a stock Ubuntu 24.04 GNOME box: **Python 3 + GTK4 via PyGObject +
  Gio D-Bus**, plus `libX11`/`libXtst` reached through **ctypes** (no compiled extensions).
- **Screenshots are blocked** on this Wayland session, which forced an unusual GUI
  verification method (see §8).

Everything below follows from these facts.

---

## 2. Technology choice: zero-install GTK4 / PyGObject / Gio

**Reasoning:** the app must run on a clean Ubuntu GNOME install with nothing extra to
install. PyGObject (`python3-gi`), GTK 4 (`gir1.2-gtk-4.0`), and the D-Bus stack are all
preinstalled on Ubuntu GNOME. That rules out Electron, Qt-via-pip, `libappindicator` (not
guaranteed present), `wl-clipboard`/`xclip` (extra binaries), and `ydotool` (needs a root
daemon). Anything we couldn't get from GTK/Gio, we reached through **ctypes** against system
libraries that are always present (`libX11`, `libXtst`).

This is why you'll see hand-rolled D-Bus interfaces and ctypes shims instead of convenient
libraries — each one is a deliberate "no new dependency" decision.

---

## 3. Clipboard history capture — the XWayland bridge

**Problem:** GNOME Wayland does **not** let a background app read the clipboard. Mutter
exposes no `wlr-data-control` protocol, and ordinary clipboard access requires the reading
window to have focus. A clipboard *manager* that only sees the clipboard when it's focused is
useless.

**What was tried / reasoned:**
- Native Wayland clipboard read → blocked without focus. Dead end.
- `wl-clipboard`'s `wl-paste --watch` → needs the `data-control` protocol Mutter lacks, and
  is an extra binary anyway. Dead end.

**Solution:** run the whole app under **XWayland** by forcing `GDK_BACKEND=x11` (the launcher
sets this automatically). On GNOME, **Mutter bridges native Wayland clipboard copies into the
X11 `CLIPBOARD` selection**, and an X11 client can watch that selection without holding focus.
So we watch the X11 clipboard via GDK's `changed` signal and read text/image asynchronously.
On a native X11 session this is a no-op — it already works.

This single decision (run under XWayland) is load-bearing for the entire app and also enables
the cursor-positioning trick in §5.

---

## 4. The tray icon — hand-rolled StatusNotifierItem + dbusmenu

There is no GTK API for a GNOME top-bar status item, and we refused to depend on
`libappindicator`. So the tray is implemented directly against the
`org.kde.StatusNotifierItem` (SNI) and `com.canonical.dbusmenu` D-Bus interfaces over Gio.

Two bugs here were instructive because both *looked* fine at the D-Bus level but rendered
nothing — the lesson that recurs throughout this project (§9):

### 4a. Icon didn't appear (0.1.1)
**Cause:** we registered the item with `RegisterStatusNotifierItem(bus_name)`. When passed a
bus name, hosts look for the item at the well-known path `/StatusNotifierItem` — but ours
lives at a custom object path, so the host found nothing there and drew no icon.
**Fix:** register by **object path** (the `busname@path` form) so the host records where the
item actually is. Diagnosed by noticing the item *was* in the watcher's registered list yet
still didn't render — proving "in the watcher list ≠ actually rendered."

### 4b. Menu didn't open on click (0.1.2)
**Cause:** the `GetLayout` serializer wrapped each child menu item in an **extra `variant`
layer**. Python's `.unpack()` tolerated the double-wrap, so our own tests passed, but the
GNOME AppIndicator extension uses GJS `deep_unpack()`, which threw
`TypeError: (destructured parameter) is not iterable` and drew no menu.
**Fix:** emit children as bare `(ia{sv}av)` variants, matching what real indicators send.
Diagnosed via `journalctl --user` (the GJS stack trace) and comparing our raw variant type
signature against a real indicator's.

---

## 5. Positioning a menu at the mouse cursor

**Problem:** Clipy's hotkey pops a menu **at the pointer**. GTK4 dropped the ability to move
a top-level window, and Wayland forbids a client from positioning its own windows in screen
coordinates at all. So neither GTK4 nor Wayland will let us place a window under the mouse.

**Solution (works because we're already under XWayland, §3):** create a tiny 1×1 host window,
mark it **override-redirect** via `XChangeWindowAttributes` (so Mutter won't manage or
reposition it), read the pointer with `XQueryPointer`, and move the host to the pointer with
`XMoveWindow` — all through `libX11` via ctypes (`clipy/x11.py`). The real menu is a
`Gtk.PopoverMenu` anchored to that host. This is the mechanism behind both the popup and,
later, the native cursor menu.

---

## 6. The UI: from a search box to Clipy's real native menu

**What I built first (wrong):** a compact **search-box popup** window — a text field with a
filterable list, Enter to paste, `1`–`9` quick-pick. It seemed like a reasonable "clipboard
chooser."

**Why it was wrong:** the user pointed out it did **not** look like Clipy's README. I pulled
Clipy's actual screenshots and confirmed: Clipy's hotkey opens a **native menu** — numbered
history entries, grouped into **folders of ten** ("0 - 9", "10 - 19", …) once there are more
than ten, snippet folders as submenus, then Clear History / Edit Snippets / Preferences /
Quit. No search box at all.

**Fix (0.2.3):** replaced the search popup with `clipy/ui/cursor_menu.py` — a real
`Gtk.PopoverMenu` built from a `Gio.Menu` model, anchored to the override-redirect host from
§5. Deleted the now-dead `ui/popup.py` and `ui/history_window.py`.

**How it was verified without screenshots:** rendered the live popover to a PNG in-process
(§8) and visually confirmed it shows numbered entries / folders / actions exactly like
Clipy's menu — not a search box.

---

## 7. Auto-paste on select — the longest thread, three iterations

Requirement: selecting an entry should **paste it into the app you were in**, not merely
update the clipboard. This took three iterations because Wayland fights input injection at
every step.

### 7a. Iteration 1 — XTEST (0.2.1)
Set the clipboard, then synthesise Ctrl+V via `libXtst`'s `XTestFakeKeyEvent`, deferred
~140ms so focus leaves our popup first.
**Why it failed:** **XTEST only delivers synthetic input to XWayland/X11 windows.** Pasting
into a *native Wayland* app did nothing. Verified directly: the keystroke never reached a
native Wayland target. XTEST is kept only as a fallback for X11/XWayland targets.

### 7b. Iteration 2 — RemoteDesktop portal (0.2.2)
The only no-root way to inject input that reaches native Wayland apps is the XDG
**RemoteDesktop portal** (`clipy/inject.py`): one persistent portal session created at
startup (`CreateSession` → `SelectDevices` keyboard, `persist_mode=2` + saved `restore_token`
→ `Start`), then `NotifyKeyboardKeycode` with evdev codes for Ctrl+V. GNOME prompts once;
the saved restore-token keeps it silent afterwards. Isolated tests showed the keystroke now
reaches a native Wayland window.

### 7c. Iteration 3 — the focus-return race (0.2.4)  ← the real bug
The user reported paste **still** didn't work — the clipboard updated but they had to press
Ctrl+V themselves. My isolated test had passed, which was itself the clue: I'd tested the
*mechanism*, not the *real flow*.

**Root-causing it properly** (with a reproduction that drives the real code path into a real
native-Wayland target across many trials):
- The cursor menu is an override-redirect window that **steals keyboard focus** while open
  (`XSetInputFocus` in `x11.move_and_focus`).
- The old code closed the menu **asynchronously** (`GLib.idle_add`) while pasting on an
  **independent 140ms timer**. Those two chains raced: the injected Ctrl+V usually fired
  *before* Mutter returned keyboard focus to the target app — so on native Wayland it went
  nowhere. Sometimes it won the race (hence "intermittent"), matching the user's experience.
- **Critical trap:** `XGetInputFocus` under XWayland only sees X windows. A native Wayland
  target has *no* X window, so X-level focus readings tell you nothing about where Mutter
  actually routes the keystroke. Don't trust them. This is why my first "focus" hypothesis
  looked refuted by the logs even though focus really was the issue.

**Fix:** a **deterministic sequence** in `CursorMenu._close`, replacing the parallel timers:
1. Close the host window **first**.
2. Restore keyboard focus to the previously-focused window (`x11.get_input_focus()` captured
   before the steal; `x11.set_input_focus()` to restore).
3. **Then** inject Ctrl+V once, after a `PASTE_SETTLE_MS = 170` settle, via `app.paste_now()`
   (a single, timer-free injection primitive).

History/snippet items now call `select_history_item/paste_text(..., paste=False)` so **only
the menu** controls paste timing; the tray path keeps the old `_try_paste` (140ms) because
the tray doesn't steal focus the same way.

**Settle tuning reasoning:** ~170ms was reliable. Too short races focus-return; **too long
(≥500ms) is actually *worse*** — focus drifts away again before we paste. So it's a tuned
window, not "bigger is safer."

**Verification:** driving the **real `CursorMenu` code path** into a genuine native-Wayland
target: **10/10** successful pastes, versus ~5/8 before the fix.

---

## 8. Verifying a GUI when screenshots are blocked

Screenshots don't work on this Wayland session, so "does it look right / did it work" couldn't
be answered the normal way. Two techniques carried the project:

- **Render a GTK4 widget to PNG in-process:** realize the widget, wrap it in a
  `Gtk.WidgetPaintable`, snapshot it (`Gtk.Snapshot` → `to_node()`), render the node with the
  native `Gsk` renderer to a `Gdk.Texture`, and `save_to_png`. Gotchas found the hard way: a
  `ScrolledWindow` has no `.snapshot` method (go through the paintable), and
  `paintable.get_current_image()` returns a `GtkRenderNodePaintable` that has **no**
  `save_to_png` — you must take the Snapshot→node→renderer→texture path. This is how the
  cursor menu was visually confirmed to look like Clipy's.
- **Test the *real flow*, not the mechanism.** Almost every time I claimed something worked
  and it didn't (tray icon, tray menu, paste), the cause was the same: I'd verified at the
  D-Bus / isolated-mechanism level, where things passed, instead of the actual user path.
  The reliable method was a two-process reproduction — a native-Wayland "target app" that
  reports what it received, driven by a simulation of the real daemon sequence — run **many
  times** to expose races.

---

## 9. The recurring lesson

The single most repeated failure mode in this project was **claiming success from a
proxy signal**:
- "The item is in the StatusNotifierWatcher's list" → but the icon still didn't render.
- "`GetLayout` unpacks fine in Python" → but GJS `deep_unpack` threw and drew no menu.
- "The portal injected Ctrl+V and my test saw text appear" → but the real flow raced focus
  and pasted nothing.

Each was fixed only by verifying the **actual observable user outcome** (icon pixels, the menu
opening, text landing in the target app), and — for the racy paste — by running the real path
**repeatedly** rather than once. Evidence before assertions.

---

## 10. Why the "remote control / screen sharing" prompt exists

A frequent question: why does auto-paste trigger a "remote control" prompt when macOS Clipy
seemingly needs nothing?

- Wayland **deliberately forbids** an app from injecting input into other apps' windows.
  There is no narrow "allow paste" permission; the only sanctioned no-root API for it is the
  **RemoteDesktop portal**, which is the same one screen-sharing tools use — so GNOME labels
  the consent dialog "remote control / screen sharing."
- macOS is **not** actually free of this. Clipy's "paste automatically after selecting"
  requires **Accessibility** permission (System Settings → Privacy → Accessibility). Without
  it, Mac Clipy also just sets the clipboard and you press ⌘V. It only *feels* invisible
  because it's a one-time system toggle labelled "Accessibility" rather than a portal prompt.
- The prompt should appear **once** (persist_mode + restore-token). Users who don't want it
  can disable auto-paste in **Preferences → General**, and the app behaves exactly like Mac
  Clipy without Accessibility — clipboard set, manual Ctrl+V. On an X11 login session the
  XTEST fallback pastes with no prompt at all.

---

## 11. Feature parity checklist (vs macOS Clipy)

- **Clipboard history** — text + images, configurable max, de-duplicated, re-copy moves to
  top. ✅
- **Snippets** — folders, manager/editor window, snippets submenu. ✅
- **Tray icon** — SNI + dbusmenu, left-click menu with history/snippets/actions. ✅
- **Native menu at the cursor** — numbered entries, folders of ten, snippet submenus,
  actions. ✅ (0.2.3)
- **Global hotkeys** — History `Ctrl+Shift+V`, Snippets `Ctrl+Shift+B`, Menu `Ctrl+Shift+C`,
  via GNOME custom shortcuts (`gsettings`). ✅
- **Type filters** — plain text / rich text / files / images, with a Type preferences tab. ✅
- **Menu options** — image thumbnails, number-from-zero, type icons, show/hide Clear History,
  reorder-after-paste, inline vs. foldered snippets. ✅
- **Confirmations** — before clearing history / deleting a snippet. ✅
- **Exclude apps** — by window class (X11/XWayland apps; native Wayland apps have no X
  WM_CLASS so this is best-effort there). ✅
- **Auto-paste on select** — clipboard set + Ctrl+V into the target app, reliable via the
  deterministic focus sequence. ✅ (0.2.4)
- **Preferences** — General / Menu / Type / Shortcuts / Applications tabs; launch-at-login. ✅
- **Persistence** — SQLite under `~/.local/share/clipy-linux/`. ✅

**Deliberately deferred** (not behaviour-critical): macOS Aqua chrome (we use native GTK
look), rich-text fidelity, sound, and auto-update.

---

## 12. Version history (the story in commits)

| Version | What changed | Why |
|---|---|---|
| 0.1.0 | Initial port: history, snippets, tray, hotkeys, search popups, prefs | First working clone |
| 0.1.1 | Register SNI by object path | Tray icon wasn't rendering |
| 0.1.2 | Emit bare `(ia{sv}av)` dbusmenu children | Tray menu wouldn't open (GJS deep_unpack) |
| 0.2.0 | Feature-parity pass: cursor popup, type filters, menu options, exclude-apps, Clipy hotkeys | Close the feature gap vs macOS |
| 0.2.1 | Auto-paste via XTEST | "Paste, don't just copy" |
| 0.2.2 | Auto-paste via RemoteDesktop portal | XTEST can't reach native Wayland apps |
| 0.2.3 | Native cursor **menu** replacing the search box | UI must match Clipy's real menu |
| 0.2.4 | Deterministic close→restore-focus→paste sequence | Auto-paste was racing focus-return |

---

## 13. Architecture map

```
clipy/
  __main__.py     entry point (forces XWayland backend)
  app.py          ClipyApplication — wiring, single-instance + --action IPC, paste sequence
  config.py       settings (JSON) + XDG paths
  models.py       HistoryItem / Snippet / SnippetFolder
  storage.py      SQLite history + snippet store (incl. touch_history for reorder-to-top)
  clipboard.py    ClipboardMonitor over GDK — text + image, focus-free via XWayland
  hotkeys.py      GNOME custom shortcuts via gsettings
  paste.py        XTEST/ydotool fallback paste
  inject.py       RemoteDesktop-portal keyboard injection (reaches native Wayland apps)
  x11.py          libX11/libXtst ctypes: pointer pos, override-redirect, focus get/set, XTEST
  sni/            hand-rolled StatusNotifierItem + com.canonical.dbusmenu (Gio D-Bus)
  ui/             cursor_menu (native menu at the pointer), snippet manager, preferences
```

Packaged as a `.deb` (`packaging/build-deb.sh`, `dpkg-deb --root-owner-group --build`,
arch:all, no fakeroot). Installs to `/usr/share/clipy`, with a `/usr/bin/clipy` launcher that
forces `GDK_BACKEND=x11`.

---

## 14. Known limitations & honest caveats

- **Auto-paste on Wayland is inherently timing-based.** There is no API to know exactly when
  the compositor has returned focus, so the 170ms settle is empirically tuned, not provably
  universal. Reliable in testing (10/10) but a particularly slow app could still miss; the
  fallback is that the content is on the clipboard and Ctrl+V always works.
- **Exclude-apps** can only see X11/XWayland window classes; native Wayland apps present no
  X `WM_CLASS`, so exclusion is best-effort for them.
- Not a pixel-for-pixel macOS look — it uses native GTK widgets by design.
```
