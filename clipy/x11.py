"""Small ``libX11`` helpers via ctypes (no extra packages).

Used for two things GTK4 can't do on its own: positioning a popup at the mouse cursor
(GTK4 dropped window-move, and Wayland forbids it — but under XWayland an
override-redirect X window can be placed freely), and best-effort detection of the app
that owns/holds focus for the clipboard (for the exclude-apps feature).

Everything degrades gracefully: if libX11 or the X11 GDK backend is unavailable, the
helpers return ``None``/no-op and callers fall back to default behaviour.
"""

from __future__ import annotations

import ctypes
import ctypes.util

_X = None


def _lib():
    global _X
    if _X is not None:
        return _X or None
    name = ctypes.util.find_library("X11")
    if not name:
        _X = False
        return None
    try:
        X = ctypes.CDLL(name)
    except OSError:
        _X = False
        return None
    X.XOpenDisplay.restype = ctypes.c_void_p
    X.XOpenDisplay.argtypes = [ctypes.c_char_p]
    X.XDefaultRootWindow.restype = ctypes.c_ulong
    X.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    X.XInternAtom.restype = ctypes.c_ulong
    X.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    X.XGetSelectionOwner.restype = ctypes.c_ulong
    X.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    X.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
    X.XFlush.argtypes = [ctypes.c_void_p]
    X.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    X.XChangeWindowAttributes.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.POINTER(_XSetWindowAttributes)]
    X.XQueryPointer.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint)]
    X.XGetInputFocus.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
    X.XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XClassHint)]
    X.XStringToKeysym.restype = ctypes.c_ulong
    X.XStringToKeysym.argtypes = [ctypes.c_char_p]
    X.XKeysymToKeycode.restype = ctypes.c_uint
    X.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    _X = X
    return X


_XTST = None


def _xtst():
    global _XTST
    if _XTST is not None:
        return _XTST or None
    name = ctypes.util.find_library("Xtst")
    if not name:
        _XTST = False
        return None
    try:
        lib = ctypes.CDLL(name)
    except OSError:
        _XTST = False
        return None
    lib.XTestFakeKeyEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    _XTST = lib
    return lib


class _XSetWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("background_pixmap", ctypes.c_ulong), ("background_pixel", ctypes.c_ulong),
        ("border_pixmap", ctypes.c_ulong), ("border_pixel", ctypes.c_ulong),
        ("bit_gravity", ctypes.c_int), ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int),
        ("event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("colormap", ctypes.c_ulong),
        ("cursor", ctypes.c_ulong)]


class _XClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_char_p), ("res_class", ctypes.c_char_p)]


_CW_OVERRIDE_REDIRECT = 1 << 9
_REVERT_TO_PARENT = 1


def pointer_position() -> tuple[int, int] | None:
    """Return the mouse pointer's (x, y) in root/screen coordinates, or None."""
    X = _lib()
    if not X:
        return None
    dpy = X.XOpenDisplay(None)
    if not dpy:
        return None
    try:
        root = X.XDefaultRootWindow(dpy)
        rr = ctypes.c_ulong(); cr = ctypes.c_ulong()
        rx = ctypes.c_int(); ry = ctypes.c_int()
        wx = ctypes.c_int(); wy = ctypes.c_int(); mask = ctypes.c_uint()
        ok = X.XQueryPointer(dpy, root, ctypes.byref(rr), ctypes.byref(cr),
                             ctypes.byref(rx), ctypes.byref(ry),
                             ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask))
        return (rx.value, ry.value) if ok else None
    finally:
        _close(dpy)


def make_override_redirect(xid: int) -> bool:
    """Mark an X window override-redirect so the WM won't manage/reposition it.

    Must be called before the window is mapped for the WM to honour it.
    """
    X = _lib()
    if not X or not xid:
        return False
    dpy = X.XOpenDisplay(None)
    if not dpy:
        return False
    try:
        attrs = _XSetWindowAttributes()
        attrs.override_redirect = 1
        X.XChangeWindowAttributes(dpy, xid, _CW_OVERRIDE_REDIRECT, ctypes.byref(attrs))
        X.XFlush(dpy)
        return True
    finally:
        _close(dpy)


def move_and_focus(xid: int, x: int, y: int) -> bool:
    """Move an X window to (x, y) and give it keyboard focus."""
    X = _lib()
    if not X or not xid:
        return False
    dpy = X.XOpenDisplay(None)
    if not dpy:
        return False
    try:
        X.XMoveWindow(dpy, xid, int(x), int(y))
        X.XSetInputFocus(dpy, xid, _REVERT_TO_PARENT, 0)
        X.XFlush(dpy)
        return True
    finally:
        _close(dpy)


def get_input_focus() -> int:
    """Return the X window id that currently holds the input focus (0 if unknown).

    Under XWayland this reports X-level focus only; native Wayland apps are invisible to
    it, but capturing/restoring it still helps X11/XWayland targets and is harmless for
    Wayland ones (Mutter restores Wayland focus itself when our popup unmaps)."""
    X = _lib()
    if not X:
        return 0
    dpy = X.XOpenDisplay(None)
    if not dpy:
        return 0
    try:
        foc = ctypes.c_ulong(); rev = ctypes.c_int()
        X.XGetInputFocus(dpy, ctypes.byref(foc), ctypes.byref(rev))
        return int(foc.value)
    finally:
        _close(dpy)


def set_input_focus(window: int) -> bool:
    """Give the input focus back to a previously-focused X window."""
    X = _lib()
    if not X or not window:
        return False
    dpy = X.XOpenDisplay(None)
    if not dpy:
        return False
    try:
        X.XSetInputFocus(dpy, window, _REVERT_TO_PARENT, 0)
        X.XFlush(dpy)
        return True
    finally:
        _close(dpy)


def _wm_class(dpy, window) -> str | None:
    X = _X
    if not window:
        return None
    hint = _XClassHint()
    if X.XGetClassHint(dpy, window, ctypes.byref(hint)):
        cls = hint.res_class or hint.res_name
        return cls.decode(errors="replace") if cls else None
    return None


def active_source_app() -> str | None:
    """Best-effort WM_CLASS of the app that likely produced the clipboard content.

    Tries the focused X window, then the CLIPBOARD selection owner. On GNOME Wayland
    native Wayland apps have no X WM_CLASS (the owner is the XWayland bridge), so this
    returns None for them — exclude-apps then only affects X11/XWayland apps.
    """
    X = _lib()
    if not X:
        return None
    dpy = X.XOpenDisplay(None)
    if not dpy:
        return None
    try:
        focus = ctypes.c_ulong(); revert = ctypes.c_int()
        X.XGetInputFocus(dpy, ctypes.byref(focus), ctypes.byref(revert))
        cls = _wm_class(dpy, focus.value)
        if cls:
            return cls
        clip = X.XInternAtom(dpy, b"CLIPBOARD", False)
        owner = X.XGetSelectionOwner(dpy, clip)
        return _wm_class(dpy, owner)
    finally:
        _close(dpy)


def synth_paste(shift: bool = False) -> bool:
    """Synthesise Ctrl+V (or Ctrl+Shift+V with ``shift``) via XTEST.

    Reaches the currently focused window. Works for X11/XWayland targets and, on Mutter,
    native Wayland windows too. Returns False if XTEST/libX11 is unavailable.
    """
    X = _lib()
    Xtst = _xtst()
    if not X or not Xtst:
        return False
    dpy = X.XOpenDisplay(None)
    if not dpy:
        return False
    try:
        ctrl = X.XKeysymToKeycode(dpy, X.XStringToKeysym(b"Control_L"))
        shift_kc = X.XKeysymToKeycode(dpy, X.XStringToKeysym(b"Shift_L"))
        v = X.XKeysymToKeycode(dpy, X.XStringToKeysym(b"v"))
        if not ctrl or not v:
            return False
        Xtst.XTestFakeKeyEvent(dpy, ctrl, 1, 0)
        if shift:
            Xtst.XTestFakeKeyEvent(dpy, shift_kc, 1, 0)
        Xtst.XTestFakeKeyEvent(dpy, v, 1, 0)
        Xtst.XTestFakeKeyEvent(dpy, v, 0, 0)
        if shift:
            Xtst.XTestFakeKeyEvent(dpy, shift_kc, 0, 0)
        Xtst.XTestFakeKeyEvent(dpy, ctrl, 0, 0)
        X.XFlush(dpy)
        return True
    finally:
        _close(dpy)


def _close(dpy) -> None:
    X = _X
    if X and dpy:
        try:
            X.XCloseDisplay.argtypes = [ctypes.c_void_p]
            X.XCloseDisplay(dpy)
        except Exception:
            pass
