"""Clipboard monitoring and writing via GDK (GTK4).

GTK talks to the compositor directly, so we need no ``wl-clipboard``/``xclip``. We watch
the default clipboard's ``changed`` signal and read text or images asynchronously.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib  # noqa: E402

# Mime type set by password managers so history tools skip the entry.
PASSWORD_HINT_MIME = "x-kde-passwordManagerHint"

CaptureFn = Callable[[str, str, bytes | None, bool], None]
# on_capture(kind, text, image_bytes, is_secret)


class ClipboardMonitor:
    def __init__(self, display: Gdk.Display, on_capture: CaptureFn):
        self.clipboard = display.get_clipboard()
        self.on_capture = on_capture
        self._suppress = False  # set while we write our own content
        self._handler = self.clipboard.connect("changed", self._on_changed)

    def stop(self) -> None:
        if self._handler:
            self.clipboard.disconnect(self._handler)
            self._handler = 0

    def capture_current(self) -> None:
        """Read whatever is on the clipboard right now (used at startup)."""
        self._on_changed(self.clipboard)

    # -- reading ---------------------------------------------------------
    def _on_changed(self, clipboard: Gdk.Clipboard) -> None:
        # Ignore content this app just placed on the clipboard.
        if self._suppress or clipboard.is_local():
            return
        formats = clipboard.get_formats()
        mimes = list(formats.get_mime_types() or [])
        is_secret = any(PASSWORD_HINT_MIME in m for m in mimes)

        # Prefer images; fall back to text.
        has_image = any(m.startswith("image/") for m in mimes) or \
            bool(formats.get_gtypes() and Gdk.Texture.__gtype__ in formats.get_gtypes())
        if has_image:
            clipboard.read_texture_async(None, self._on_texture, is_secret)
        else:
            clipboard.read_text_async(None, self._on_text, is_secret)

    def _on_text(self, clipboard: Gdk.Clipboard, res: Gio.AsyncResult, is_secret: bool) -> None:
        try:
            text = clipboard.read_text_finish(res)
        except GLib.Error:
            return
        if text is None or text == "":
            return
        self.on_capture("text", text, None, is_secret)

    def _on_texture(self, clipboard: Gdk.Clipboard, res: Gio.AsyncResult, is_secret: bool) -> None:
        try:
            texture = clipboard.read_texture_finish(res)
        except GLib.Error:
            # Some sources advertise an image but only serve text; try text.
            clipboard.read_text_async(None, self._on_text, is_secret)
            return
        if texture is None:
            return
        try:
            png = texture.save_to_png_bytes()
            data = bytes(png.get_data())
        except Exception:
            return
        self.on_capture("image", "", data, is_secret)

    # -- writing ---------------------------------------------------------
    def set_text(self, text: str) -> None:
        self._suppress = True
        self.clipboard.set(text)
        GLib.idle_add(self._release_suppress)

    def set_image_file(self, path: str) -> None:
        try:
            texture = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            return
        self._suppress = True
        self.clipboard.set(texture)
        GLib.idle_add(self._release_suppress)

    def _release_suppress(self) -> bool:
        self._suppress = False
        return False  # one-shot
