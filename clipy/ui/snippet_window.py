"""Snippet manager: folders, snippets, and an editor — mirrors Clipy's snippet editor."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402


class SnippetWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Clipy — Snippets")
        self.clipy = app
        self.set_default_size(720, 460)
        self.current_folder = None
        self.current_snippet = None

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=200)
        self.set_child(paned)

        # Left: folders
        folder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        folder_box.set_margin_top(6); folder_box.set_margin_bottom(6)
        folder_box.set_margin_start(6); folder_box.set_margin_end(6)
        folder_box.append(self._heading("Folders"))
        fscroll = Gtk.ScrolledWindow(vexpand=True)
        self.folder_list = Gtk.ListBox()
        self.folder_list.connect("row-selected", self._on_folder_selected)
        fscroll.set_child(self.folder_list)
        folder_box.append(fscroll)
        folder_box.append(self._button_row(self._add_folder, self._remove_folder,
                                           self._rename_folder))
        paned.set_start_child(folder_box)

        # Right: snippets + editor
        right = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=220)
        paned.set_end_child(right)

        snip_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        snip_box.set_margin_top(6); snip_box.set_margin_bottom(6)
        snip_box.set_margin_start(6); snip_box.set_margin_end(6)
        snip_box.append(self._heading("Snippets"))
        sscroll = Gtk.ScrolledWindow(vexpand=True)
        self.snippet_list = Gtk.ListBox()
        self.snippet_list.connect("row-selected", self._on_snippet_selected)
        sscroll.set_child(self.snippet_list)
        snip_box.append(sscroll)
        snip_box.append(self._button_row(self._add_snippet, self._remove_snippet, None))
        right.set_start_child(snip_box)

        editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        editor.set_margin_top(6); editor.set_margin_bottom(6)
        editor.set_margin_start(6); editor.set_margin_end(6)
        editor.append(self._heading("Title"))
        self.title_entry = Gtk.Entry()
        self.title_entry.connect("changed", lambda *_: self._save_current())
        editor.append(self.title_entry)
        editor.append(self._heading("Content"))
        cscroll = Gtk.ScrolledWindow(vexpand=True)
        self.content_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.content_view.get_buffer().connect("changed", lambda *_: self._save_current())
        cscroll.set_child(self.content_view)
        editor.append(cscroll)
        right.set_end_child(editor)

        self._suspend_save = False
        self.reload_folders()

    # -- widgets helpers -------------------------------------------------
    def _heading(self, text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class("heading")
        return lbl

    def _button_row(self, on_add, on_remove, on_edit) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        add = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add.connect("clicked", lambda *_: on_add())
        row.append(add)
        rem = Gtk.Button.new_from_icon_name("list-remove-symbolic")
        rem.connect("clicked", lambda *_: on_remove())
        row.append(rem)
        if on_edit:
            edit = Gtk.Button.new_from_icon_name("document-edit-symbolic")
            edit.connect("clicked", lambda *_: on_edit())
            row.append(edit)
        return row

    # -- folders ---------------------------------------------------------
    def reload_folders(self) -> None:
        self._clear(self.folder_list)
        for folder in self.clipy.store.folders():
            row = Gtk.ListBoxRow()
            row.folder = folder  # type: ignore[attr-defined]
            row.set_child(Gtk.Label(label=folder.name, xalign=0, margin_top=4,
                                    margin_bottom=4, margin_start=6))
            self.folder_list.append(row)
        first = self.folder_list.get_row_at_index(0)
        if first:
            self.folder_list.select_row(first)
        else:
            self.current_folder = None
            self.reload_snippets()

    def _on_folder_selected(self, _lb, row) -> None:
        self.current_folder = getattr(row, "folder", None) if row else None
        self.reload_snippets()

    def _add_folder(self) -> None:
        f = self.clipy.store.add_folder("New Folder")
        self.reload_folders()
        self.clipy.rebuild_menu()
        self._select_folder_id(f.id)

    def _remove_folder(self) -> None:
        if self.current_folder:
            self.clipy.store.delete_folder(self.current_folder.id)
            self.reload_folders()
            self.clipy.rebuild_menu()

    def _rename_folder(self) -> None:
        if not self.current_folder:
            return
        dialog = _TextPrompt(self, "Rename folder", self.current_folder.name)
        dialog.run_async(lambda name: self._do_rename_folder(name))

    def _do_rename_folder(self, name: str) -> None:
        if name and self.current_folder:
            self.clipy.store.rename_folder(self.current_folder.id, name)
            self.reload_folders()
            self.clipy.rebuild_menu()

    def _select_folder_id(self, folder_id: int) -> None:
        i = 0
        while (row := self.folder_list.get_row_at_index(i)) is not None:
            if getattr(row, "folder").id == folder_id:
                self.folder_list.select_row(row)
                return
            i += 1

    # -- snippets --------------------------------------------------------
    def reload_snippets(self) -> None:
        self._clear(self.snippet_list)
        if self.current_folder:
            for snip in self.clipy.store.snippets(self.current_folder.id):
                row = Gtk.ListBoxRow()
                row.snippet = snip  # type: ignore[attr-defined]
                row.set_child(Gtk.Label(label=snip.title or "(untitled)", xalign=0,
                                        margin_top=4, margin_bottom=4, margin_start=6))
                self.snippet_list.append(row)
        first = self.snippet_list.get_row_at_index(0)
        self.snippet_list.select_row(first) if first else self._load_editor(None)

    def _on_snippet_selected(self, _lb, row) -> None:
        self._load_editor(getattr(row, "snippet", None) if row else None)

    def _load_editor(self, snippet) -> None:
        self._suspend_save = True
        self.current_snippet = snippet
        self.title_entry.set_text(snippet.title if snippet else "")
        self.content_view.get_buffer().set_text(snippet.content if snippet else "")
        self.title_entry.set_sensitive(snippet is not None)
        self.content_view.set_sensitive(snippet is not None)
        self._suspend_save = False

    def _add_snippet(self) -> None:
        if not self.current_folder:
            return
        s = self.clipy.store.add_snippet(self.current_folder.id, "New Snippet", "")
        self.reload_snippets()
        self.clipy.rebuild_menu()
        i = 0
        while (row := self.snippet_list.get_row_at_index(i)) is not None:
            if getattr(row, "snippet").id == s.id:
                self.snippet_list.select_row(row)
                self.title_entry.grab_focus()
                return
            i += 1

    def _remove_snippet(self) -> None:
        if self.current_snippet:
            self.clipy.store.delete_snippet(self.current_snippet.id)
            self.reload_snippets()
            self.clipy.rebuild_menu()

    def _save_current(self) -> None:
        if self._suspend_save or not self.current_snippet:
            return
        buf = self.content_view.get_buffer()
        content = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        title = self.title_entry.get_text()
        self.clipy.store.update_snippet(self.current_snippet.id, title, content)
        # Update the visible row label live.
        row = self.snippet_list.get_selected_row()
        if row:
            row.get_child().set_label(title or "(untitled)")
        self.clipy.rebuild_menu_soon()

    # -- misc ------------------------------------------------------------
    def _clear(self, listbox: Gtk.ListBox) -> None:
        child = listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            listbox.remove(child)
            child = nxt


class SnippetPicker(Gtk.ApplicationWindow):
    """Quick searchable snippet chooser — the target of the snippets hotkey.

    Type to filter, Enter/click to paste the snippet's content, Esc to close.
    """

    def __init__(self, app):
        super().__init__(application=app, title="Clipy — Snippets")
        self.clipy = app
        self.set_default_size(420, 380)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(box)
        self.search = Gtk.SearchEntry(placeholder_text="Search snippets…",
                                      margin_top=8, margin_bottom=8,
                                      margin_start=8, margin_end=8)
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        self.search.connect("activate", lambda *_: self._activate_selected())
        box.append(self.search)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_filter_func(self._filter_row)
        self.listbox.connect("row-activated", lambda _lb, row: self._paste_row(row))
        scroller.set_child(self.listbox)
        box.append(scroller)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)
        self.populate()

    def populate(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt
        for folder in self.clipy.store.folders():
            if not folder.enabled:
                continue
            for snip in self.clipy.store.snippets(folder.id):
                if not snip.enabled:
                    continue
                row = Gtk.ListBoxRow()
                row.content = snip.content  # type: ignore[attr-defined]
                row.search_text = f"{folder.name} {snip.title} {snip.content}".lower()
                lbl = Gtk.Label(label=f"{folder.name}  ›  {snip.title or '(untitled)'}",
                                xalign=0, margin_top=6, margin_bottom=6, margin_start=10)
                row.set_child(lbl)
                self.listbox.append(row)
        first = self.listbox.get_row_at_index(0)
        if first:
            self.listbox.select_row(first)

    def _filter_row(self, row) -> bool:
        text = self.search.get_text().strip().lower()
        return not text or text in getattr(row, "search_text", "")

    def _on_key(self, _c, keyval, _kc, _state) -> bool:
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
            rows = [r for i in range(9999)
                    if (r := self.listbox.get_row_at_index(i)) and self._filter_row(r)]
            if not rows:
                return True
            cur = self.listbox.get_selected_row()
            idx = rows.index(cur) if cur in rows else -1
            idx = max(0, min(len(rows) - 1, idx + (1 if keyval == Gdk.KEY_Down else -1)))
            self.listbox.select_row(rows[idx])
            rows[idx].grab_focus()
            return True
        return False

    def _activate_selected(self) -> None:
        row = self.listbox.get_selected_row()
        if row:
            self._paste_row(row)

    def _paste_row(self, row) -> None:
        content = getattr(row, "content", None)
        if content is not None:
            self.close()
            self.clipy.paste_text(content)


class _TextPrompt(Gtk.Window):
    """Tiny modal text prompt (GTK4 dropped Gtk.Dialog convenience)."""

    def __init__(self, parent, title, initial=""):
        super().__init__(title=title, transient_for=parent, modal=True)
        self.set_default_size(320, -1)
        self._cb = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(12); box.set_margin_end(12)
        self.entry = Gtk.Entry(text=initial)
        self.entry.connect("activate", lambda *_: self._accept())
        box.append(self.entry)
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel"); cancel.connect("clicked", lambda *_: self.close())
        ok = Gtk.Button(label="OK"); ok.add_css_class("suggested-action")
        ok.connect("clicked", lambda *_: self._accept())
        btns.append(cancel); btns.append(ok)
        box.append(btns)
        self.set_child(box)

    def run_async(self, callback):
        self._cb = callback
        self.present()
        self.entry.grab_focus()

    def _accept(self):
        text = self.entry.get_text().strip()
        self.close()
        if self._cb:
            self._cb(text)
