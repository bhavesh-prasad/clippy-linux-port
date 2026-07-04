"""Best-effort auto-paste (synthesise Ctrl+V).

Reliable only for X11/XWayland target windows. Tries, in order: ``ydotool`` (works on
Wayland if the daemon is running), then XTEST via python-xlib. If neither is available the
caller falls back to leaving the content on the clipboard for a manual paste.
"""

from __future__ import annotations

import shutil
import subprocess


def send_paste() -> bool:
    # Preferred: XTEST via libX11/libXtst (ctypes, zero install) — reaches the focused
    # window on X11/XWayland and, on Mutter, native Wayland windows too.
    try:
        from . import x11
        if x11.synth_paste():
            return True
    except Exception:
        pass
    if _ydotool():
        return True
    if _xtest():
        return True
    return False


def _ydotool() -> bool:
    if not shutil.which("ydotool"):
        return False
    try:
        # 29 = KEY_LEFTCTRL, 47 = KEY_V (Linux input event codes)
        subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                       check=True, timeout=2)
        return True
    except Exception:
        return False


def _xtest() -> bool:
    try:
        from Xlib import X, XK  # type: ignore
        from Xlib.display import Display  # type: ignore
        from Xlib.ext.xtest import fake_input  # type: ignore
    except Exception:
        return False
    try:
        disp = Display()
        ctrl = disp.keysym_to_keycode(XK.string_to_keysym("Control_L"))
        v = disp.keysym_to_keycode(XK.string_to_keysym("v"))
        fake_input(disp, X.KeyPress, ctrl)
        fake_input(disp, X.KeyPress, v)
        fake_input(disp, X.KeyRelease, v)
        fake_input(disp, X.KeyRelease, ctrl)
        disp.sync()
        return True
    except Exception:
        return False
