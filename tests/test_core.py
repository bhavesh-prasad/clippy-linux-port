"""Unit tests for the display-independent core (storage, models, dbusmenu tree)."""

import os
import tempfile
import unittest
from pathlib import Path

from clipy.models import HistoryItem
from clipy.storage import Store, content_hash


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(Path(self.dir) / "t.db")

    def tearDown(self):
        self.store.close()

    def test_add_and_dedupe_consecutive(self):
        self.assertIsNotNone(self.store.add_text("hello"))
        self.assertIsNone(self.store.add_text("hello"))  # same as latest -> skip
        self.assertEqual(len(self.store.history()), 1)

    def test_recopy_moves_to_top(self):
        self.store.add_text("a")
        self.store.add_text("b")
        self.store.add_text("a")  # existing, moves to top, no duplicate
        self.assertEqual([i.text for i in self.store.history()], ["a", "b"])

    def test_trim(self):
        for i in range(10):
            self.store.add_text(f"item{i}")
        self.store.trim_history(3)
        self.assertEqual(len(self.store.history()), 3)
        self.assertEqual(self.store.history()[0].text, "item9")

    def test_image_roundtrip(self):
        item = self.store.add_image(b"\x89PNG-bytes")
        self.assertIsNotNone(item)
        self.assertEqual(item.kind, "image")
        self.assertTrue(os.path.exists(item.image_path))
        self.assertIsNone(self.store.add_image(b"\x89PNG-bytes"))  # dedupe latest

    def test_snippets(self):
        self.store.seed_default_snippets()
        folders = self.store.folders()
        self.assertEqual(len(folders), 1)
        snips = self.store.snippets(folders[0].id)
        self.assertEqual(len(snips), 2)
        s = self.store.add_snippet(folders[0].id, "T", "C")
        self.store.update_snippet(s.id, "T2", "C2")
        self.assertEqual(self.store.get_snippet(s.id).title, "T2")
        self.store.delete_snippet(s.id)
        self.assertIsNone(self.store.get_snippet(s.id))

    def test_clear_and_delete(self):
        a = self.store.add_text("a")
        self.store.add_text("b")
        self.store.delete_history(a.id)
        self.assertEqual([i.text for i in self.store.history()], ["b"])
        self.store.clear_history()
        self.assertEqual(self.store.history(), [])


class TouchTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(Path(self.dir) / "t.db")

    def tearDown(self):
        self.store.close()

    def test_touch_moves_to_top(self):
        a = self.store.add_text("a")
        self.store.add_text("b")
        self.store.add_text("c")
        self.store.touch_history(a.id)  # move "a" back to the top
        self.assertEqual(self.store.history()[0].text, "a")


class ClassifyTest(unittest.TestCase):
    def test_categories(self):
        from clipy.clipboard import ClipboardMonitor as M
        self.assertEqual(M._classify(["image/png"], True), "image")
        self.assertEqual(M._classify(["text/uri-list", "text/plain"], False), "files")
        self.assertEqual(M._classify(["text/html", "text/plain"], False), "rich_text")
        self.assertEqual(M._classify(["text/plain"], False), "text")
        self.assertEqual(M._classify([], False), "text")


class HashTest(unittest.TestCase):
    def test_text_hash_stable(self):
        self.assertEqual(content_hash("text", "x", None),
                         content_hash("text", "x", None))
        self.assertNotEqual(content_hash("text", "x", None),
                            content_hash("text", "y", None))

    def test_image_hash_uses_bytes(self):
        self.assertEqual(content_hash("image", "", b"1"),
                         content_hash("image", "", b"1"))
        self.assertNotEqual(content_hash("image", "", b"1"),
                            content_hash("image", "", b"2"))


class PreviewTest(unittest.TestCase):
    def test_text_preview_collapses_and_truncates(self):
        item = HistoryItem(1, "text", "a\n  b\tc" + "x" * 100, None, None, "h", 0.0)
        p = item.preview(10)
        self.assertLessEqual(len(p), 10)
        self.assertNotIn("\n", p)

    def test_image_preview(self):
        item = HistoryItem(1, "image", "", "/tmp/x.png", None, "h", 0.0)
        self.assertIn("Image", item.preview())

    def test_empty_preview(self):
        item = HistoryItem(1, "text", "", None, None, "h", 0.0)
        self.assertEqual(item.preview(), "(empty)")


class DbusMenuTreeTest(unittest.TestCase):
    """Exercises the menu tree indexing/serialisation without a bus connection."""

    def test_reindex_and_serialize(self):
        from clipy.sni.dbusmenu import DbusMenu, MenuItem
        menu = DbusMenu()
        clicked = []
        root = MenuItem(children=[
            MenuItem("A", action=lambda: clicked.append("A")),
            MenuItem(separator=True),
            MenuItem("Sub", children=[MenuItem("Child", action=lambda: clicked.append("C"))]),
        ])
        menu.set_root(root)
        # ids assigned depth-first, unique
        ids = sorted(menu._by_id)
        self.assertEqual(ids, [0, 1, 2, 3, 4])
        # serialize full tree
        rid, props, children = menu._serialize(menu.root, -1, None)
        self.assertEqual(rid, 0)
        self.assertEqual(len(children), 3)
        # activating an item id runs its callback
        menu._by_id[1].action()
        self.assertIn("A", clicked)

    def test_separator_and_submenu_props(self):
        from clipy.sni.dbusmenu import MenuItem
        sep = MenuItem(separator=True)
        self.assertEqual(sep.properties()["type"].get_string(), "separator")
        parent = MenuItem("P", children=[MenuItem("c")])
        self.assertEqual(parent.properties()["children-display"].get_string(), "submenu")

    def test_getlayout_child_wire_shape(self):
        """Regression: each `av` child must contain a bare (ia{sv}av), not a nested v.

        GJS's deep_unpack() (GNOME AppIndicator extension) throws on the double-wrapped
        form, so the menu silently fails to render. Python's .unpack() hides the bug,
        which is why this asserts on the raw GLib.Variant types.
        """
        from gi.repository import GLib
        from clipy.sni.dbusmenu import DbusMenu, MenuItem
        menu = DbusMenu()
        menu.set_root(MenuItem(children=[MenuItem("A"), MenuItem("B")]))
        # Build the GetLayout reply exactly as the D-Bus handler does.
        layout = menu._serialize(menu.root, -1, None)
        reply = GLib.Variant("(u(ia{sv}av))", (menu.revision, layout))
        children = reply.get_child_value(1).get_child_value(2)  # the `av`
        self.assertGreater(children.n_children(), 0)
        element = children.get_child_value(0)
        self.assertEqual(element.get_type_string(), "v")
        self.assertEqual(element.get_variant().get_type_string(), "(ia{sv}av)")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Expanded test suite — appended below
# ---------------------------------------------------------------------------

class StorageEdgeTest(unittest.TestCase):
    """Edge cases for Store that complement the basic StorageTest."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(Path(self.dir) / "t.db")

    def tearDown(self):
        self.store.close()

    def test_add_text_empty_string(self):
        """Empty string is valid content and should be stored."""
        item = self.store.add_text("")
        self.assertIsNotNone(item)
        self.assertEqual(item.text, "")
        self.assertEqual(item.kind, "text")

    def test_get_history_nonexistent(self):
        """get_history with a missing id returns None."""
        self.assertIsNone(self.store.get_history(99999))

    def test_history_limit(self):
        """history(limit=2) returns at most 2 items even when more exist."""
        for i in range(5):
            self.store.add_text(f"item{i}")
        result = self.store.history(limit=2)
        self.assertEqual(len(result), 2)

    def test_dedupe_non_consecutive(self):
        """Adding A, B, A should store only 2 unique items (A moved to top)."""
        self.store.add_text("A")
        self.store.add_text("B")
        self.store.add_text("A")  # deduped: old A deleted, new A inserted at top
        items = self.store.history()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].text, "A")
        self.assertEqual(items[1].text, "B")

    def test_trim_noop_when_under_limit(self):
        """trim_history(100) keeps all items when fewer than 100 exist."""
        for i in range(3):
            self.store.add_text(f"x{i}")
        self.store.trim_history(100)
        self.assertEqual(len(self.store.history()), 3)

    def test_delete_nonexistent_is_noop(self):
        """delete_history with a missing id must not raise."""
        try:
            self.store.delete_history(99999)
        except Exception as exc:
            self.fail(f"delete_history raised unexpectedly: {exc}")

    def test_latest_hash_empty(self):
        """On a fresh store, latest_hash() returns None."""
        self.assertIsNone(self.store.latest_hash())


class FolderTest(unittest.TestCase):
    """CRUD operations on snippet folders."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(Path(self.dir) / "t.db")

    def tearDown(self):
        self.store.close()

    def test_add_folder(self):
        """add_folder returns a SnippetFolder with the right name and enabled=True."""
        from clipy.models import SnippetFolder
        f = self.store.add_folder("F")
        self.assertIsInstance(f, SnippetFolder)
        self.assertEqual(f.name, "F")
        self.assertTrue(f.enabled)

    def test_rename_folder(self):
        """rename_folder persists the new name."""
        f = self.store.add_folder("Old")
        self.store.rename_folder(f.id, "New")
        folders = self.store.folders()
        self.assertEqual(folders[0].name, "New")

    def test_delete_folder_cascades(self):
        """Deleting a folder also removes its child snippets (FK CASCADE)."""
        f = self.store.add_folder("ToDelete")
        s = self.store.add_snippet(f.id, "Title", "Content")
        self.store.delete_folder(f.id)
        self.assertEqual(self.store.folders(), [])
        self.assertIsNone(self.store.get_snippet(s.id))

    def test_set_folder_enabled(self):
        """set_folder_enabled toggles the enabled flag and persists it."""
        f = self.store.add_folder("F")
        self.store.set_folder_enabled(f.id, False)
        folders = self.store.folders()
        self.assertFalse(folders[0].enabled)
        self.store.set_folder_enabled(f.id, True)
        folders = self.store.folders()
        self.assertTrue(folders[0].enabled)

    def test_multiple_folders_ordering(self):
        """Two folders are returned in insertion order."""
        f1 = self.store.add_folder("First")
        f2 = self.store.add_folder("Second")
        folders = self.store.folders()
        self.assertEqual(len(folders), 2)
        self.assertEqual(folders[0].id, f1.id)
        self.assertEqual(folders[1].id, f2.id)


class SnippetEdgeTest(unittest.TestCase):
    """Snippet edge cases beyond the basic StorageTest.test_snippets."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(Path(self.dir) / "t.db")
        self.folder = self.store.add_folder("TestFolder")

    def tearDown(self):
        self.store.close()

    def test_snippet_enable_disable(self):
        """set_snippet_enabled(id, False) persists the disabled state."""
        s = self.store.add_snippet(self.folder.id, "T", "C")
        self.store.set_snippet_enabled(s.id, False)
        loaded = self.store.get_snippet(s.id)
        self.assertFalse(loaded.enabled)

    def test_get_all_snippets_no_folder_filter(self):
        """store.snippets() with no folder_id returns snippets from all folders."""
        f2 = self.store.add_folder("Other")
        self.store.add_snippet(self.folder.id, "T1", "C1")
        self.store.add_snippet(f2.id, "T2", "C2")
        all_snippets = self.store.snippets()
        self.assertEqual(len(all_snippets), 2)

    def test_add_snippet_empty_content(self):
        """add_snippet with empty content string stores without error."""
        s = self.store.add_snippet(self.folder.id, "Title", "")
        self.assertIsNotNone(s)
        self.assertEqual(s.content, "")

    def test_update_snippet_content(self):
        """update_snippet persists the new title and content."""
        s = self.store.add_snippet(self.folder.id, "Original", "OldContent")
        self.store.update_snippet(s.id, "Updated", "NewContent")
        loaded = self.store.get_snippet(s.id)
        self.assertEqual(loaded.title, "Updated")
        self.assertEqual(loaded.content, "NewContent")


class SettingsTest(unittest.TestCase):
    """Settings load/save round-trip using temporary paths."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._settings_path = Path(self._tmp) / "settings.json"

    def test_defaults(self):
        """Freshly constructed Settings has the expected defaults."""
        from clipy.config import Settings, DEFAULT_HOTKEYS
        s = Settings()
        self.assertEqual(s.max_history, 30)
        self.assertTrue(s.paste_after_select)
        self.assertEqual(s.hotkeys, DEFAULT_HOTKEYS)

    def test_save_and_reload(self):
        """Saved settings round-trip correctly when loaded from the same path."""
        import unittest.mock as mock
        import clipy.config as cfg
        from clipy.config import Settings

        s = Settings()
        s.max_history = 99
        s.paste_after_select = False
        s.hotkeys["history"] = "<Super>h"

        with mock.patch.object(cfg, "SETTINGS_PATH", self._settings_path):
            s.save()
            loaded = Settings.load()

        self.assertEqual(loaded.max_history, 99)
        self.assertFalse(loaded.paste_after_select)
        self.assertEqual(loaded.hotkeys["history"], "<Super>h")

    def test_load_ignores_unknown_keys(self):
        """JSON with extra unknown keys loads without error; known keys preserved."""
        import json
        import unittest.mock as mock
        import clipy.config as cfg
        from clipy.config import Settings

        data = {"max_history": 15, "unknown_future_key": "ignored_value"}
        self._settings_path.write_text(json.dumps(data))

        with mock.patch.object(cfg, "SETTINGS_PATH", self._settings_path):
            loaded = Settings.load()

        self.assertEqual(loaded.max_history, 15)
        self.assertFalse(hasattr(loaded, "unknown_future_key"))

    def test_hotkeys_defaults_filled_in(self):
        """If a hotkey key is missing from JSON, it gets the default value on load."""
        import json
        import unittest.mock as mock
        import clipy.config as cfg
        from clipy.config import Settings, DEFAULT_HOTKEYS

        # Only include one hotkey; the others should be filled from DEFAULT_HOTKEYS.
        data = {"hotkeys": {"history": "<Super>h"}}
        self._settings_path.write_text(json.dumps(data))

        with mock.patch.object(cfg, "SETTINGS_PATH", self._settings_path):
            loaded = Settings.load()

        self.assertEqual(loaded.hotkeys["history"], "<Super>h")
        self.assertEqual(loaded.hotkeys["snippets"], DEFAULT_HOTKEYS["snippets"])
        self.assertEqual(loaded.hotkeys["menu"], DEFAULT_HOTKEYS["menu"])

    def test_partial_settings_merge(self):
        """Only some keys in JSON; others stay at their default values."""
        import json
        import unittest.mock as mock
        import clipy.config as cfg
        from clipy.config import Settings

        data = {"max_history": 50}
        self._settings_path.write_text(json.dumps(data))

        with mock.patch.object(cfg, "SETTINGS_PATH", self._settings_path):
            loaded = Settings.load()

        self.assertEqual(loaded.max_history, 50)
        # Other fields should be at defaults
        self.assertTrue(loaded.paste_after_select)
        self.assertTrue(loaded.reorder_after_paste)


class ClassifyExtendedTest(unittest.TestCase):
    """Additional coverage for ClipboardMonitor._classify."""

    def _classify(self, mimes, has_image=False):
        from clipy.clipboard import ClipboardMonitor as M
        return M._classify(mimes, has_image)

    def test_rtf_mime(self):
        self.assertEqual(self._classify(["text/rtf", "text/plain"]), "rich_text")

    def test_html_mime(self):
        self.assertEqual(self._classify(["text/html"]), "rich_text")

    def test_uri_list(self):
        self.assertEqual(self._classify(["text/uri-list"]), "files")

    def test_x_special(self):
        self.assertEqual(
            self._classify(["x-special/gnome-copied-files", "text/plain"]), "files"
        )

    def test_image_flag_overrides_text(self):
        """has_image=True should return 'image' even when mimes contain text/plain."""
        self.assertEqual(self._classify(["text/plain"], has_image=True), "image")

    def test_empty_mimes_no_image(self):
        """Empty mime list with no image flag falls back to 'text'."""
        self.assertEqual(self._classify([], has_image=False), "text")


class ContentHashTest(unittest.TestCase):
    """Additional coverage for the content_hash helper."""

    def test_different_kinds_different_hash(self):
        """Hashes for 'text' and 'image' kinds differ even with the same text."""
        h_text = content_hash("text", "x", None)
        h_image = content_hash("image", "x", None)
        self.assertNotEqual(h_text, h_image)

    def test_image_ignores_text_field(self):
        """For images the text field is ignored; only bytes matter."""
        h1 = content_hash("image", "ignored", b"data")
        h2 = content_hash("image", "", b"data")
        self.assertEqual(h1, h2)

    def test_empty_bytes_image(self):
        """content_hash for an image with empty bytes should not raise."""
        try:
            result = content_hash("image", "", b"")
            self.assertIsInstance(result, str)
        except Exception as exc:
            self.fail(f"content_hash raised unexpectedly: {exc}")


class MenuItemTest(unittest.TestCase):
    """MenuItem property generation without a real D-Bus connection."""

    def test_label_property(self):
        """An item with a label has 'label' in its properties dict."""
        from clipy.sni.dbusmenu import MenuItem
        item = MenuItem("Hello")
        props = item.properties()
        self.assertIn("label", props)
        self.assertEqual(props["label"].get_string(), "Hello")

    def test_disabled_item_property(self):
        """enabled=False should appear as 'enabled': False in properties."""
        from clipy.sni.dbusmenu import MenuItem
        item = MenuItem("X", enabled=False)
        props = item.properties()
        self.assertIn("enabled", props)
        self.assertFalse(props["enabled"].get_boolean())

    def test_toggle_properties(self):
        """toggle_type and toggle_state are reflected in properties."""
        from clipy.sni.dbusmenu import MenuItem
        item = MenuItem("Check", toggle_type="checkmark", toggle_state=1)
        props = item.properties()
        self.assertEqual(props["toggle-type"].get_string(), "checkmark")
        self.assertEqual(props["toggle-state"].get_int32(), 1)

    def test_icon_name_property(self):
        """icon_name set on an item appears as 'icon-name' in properties."""
        from clipy.sni.dbusmenu import MenuItem
        item = MenuItem("Icon", icon_name="edit-copy")
        props = item.properties()
        self.assertIn("icon-name", props)
        self.assertEqual(props["icon-name"].get_string(), "edit-copy")

    def test_invisible_item_excluded_from_children(self):
        """An invisible child must not appear in the serialized tree."""
        from clipy.sni.dbusmenu import DbusMenu, MenuItem
        menu = DbusMenu()
        root = MenuItem(children=[
            MenuItem("Visible"),
            MenuItem("Hidden", visible=False),
        ])
        menu.set_root(root)
        _id, _props, children = menu._serialize(menu.root, -1, None)
        # Only the visible child should be included
        self.assertEqual(len(children), 1)

    def test_filter_names(self):
        """properties(names=['label']) returns only the requested key."""
        from clipy.sni.dbusmenu import MenuItem
        item = MenuItem("Hello", icon_name="edit-copy")
        props = item.properties(names=["label"])
        self.assertIn("label", props)
        self.assertNotIn("icon-name", props)


class DbusMenuTest(unittest.TestCase):
    """Extended DbusMenu tree tests."""

    def test_revision_increments_on_set_root(self):
        """revision should increment each time set_root is called."""
        from clipy.sni.dbusmenu import DbusMenu, MenuItem
        menu = DbusMenu()
        initial = menu.revision
        menu.set_root(MenuItem(children=[MenuItem("A")]))
        self.assertEqual(menu.revision, initial + 1)
        menu.set_root(MenuItem(children=[MenuItem("B")]))
        self.assertEqual(menu.revision, initial + 2)

    def test_disabled_item_not_activated(self):
        """_activate on a disabled item must not call its action."""
        from clipy.sni.dbusmenu import DbusMenu, MenuItem
        called = []
        menu = DbusMenu()
        menu.set_root(MenuItem(children=[
            MenuItem("Disabled", action=lambda: called.append(True), enabled=False),
        ]))
        disabled_id = list(menu._by_id.keys())[1]
        menu._activate(disabled_id)
        self.assertEqual(called, [])

    def test_unknown_item_activate_noop(self):
        """_activate with a non-existent id must not raise."""
        from clipy.sni.dbusmenu import DbusMenu
        menu = DbusMenu()
        try:
            menu._activate(99999)
        except Exception as exc:
            self.fail(f"_activate raised unexpectedly: {exc}")

    def test_depth_zero_no_children(self):
        """_serialize with depth=0 returns an empty children list."""
        from clipy.sni.dbusmenu import DbusMenu, MenuItem
        menu = DbusMenu()
        menu.set_root(MenuItem(children=[MenuItem("A"), MenuItem("B")]))
        _id, _props, children = menu._serialize(menu.root, 0, None)
        self.assertEqual(children, [])

    def test_get_layout_depth_one(self):
        """depth=1 includes direct children but not grandchildren."""
        from clipy.sni.dbusmenu import DbusMenu, MenuItem
        menu = DbusMenu()
        root = MenuItem(children=[
            MenuItem("Parent", children=[MenuItem("Grandchild")]),
        ])
        menu.set_root(root)
        _id, _props, children = menu._serialize(menu.root, 1, None)
        # There should be one direct child
        self.assertEqual(len(children), 1)
        from gi.repository import GLib
        # Unwrap the 'v' variant to get (id, props, grandchildren)
        child_tuple = children[0].get_variant()
        grandchildren = child_tuple.get_child_value(2)  # the av of grandchildren
        self.assertEqual(grandchildren.n_children(), 0)


class PreviewExtendedTest(unittest.TestCase):
    """HistoryItem.preview() edge cases."""

    def test_long_text_truncated_with_ellipsis(self):
        """Text longer than max_len is truncated and ends with the ellipsis character."""
        item = HistoryItem(1, "text", "A" * 100, None, None, "h", 0.0)
        preview = item.preview(max_len=10)
        self.assertTrue(preview.endswith("…"))
        self.assertLessEqual(len(preview), 10)

    def test_whitespace_collapsed(self):
        """Multiple spaces and newlines are collapsed to a single space."""
        item = HistoryItem(1, "text", "hello\n  world\t!", None, None, "h", 0.0)
        preview = item.preview(max_len=100)
        self.assertNotIn("\n", preview)
        self.assertNotIn("  ", preview)
        self.assertEqual(preview, "hello world !")

    def test_exact_max_len(self):
        """Text exactly at max_len is returned as-is without truncation."""
        text = "A" * 10
        item = HistoryItem(1, "text", text, None, None, "h", 0.0)
        preview = item.preview(max_len=10)
        self.assertEqual(preview, text)
        self.assertFalse(preview.endswith("…"))

    def test_custom_max_len(self):
        """preview(max_len=5) truncates to at most 5 characters."""
        item = HistoryItem(1, "text", "Hello World", None, None, "h", 0.0)
        preview = item.preview(max_len=5)
        self.assertLessEqual(len(preview), 5)
        self.assertTrue(preview.endswith("…"))


class HotkeyPathTest(unittest.TestCase):
    """Pure path logic for hotkeys — no gsettings required."""

    def test_path_for_history(self):
        """_path_for('history') ends with 'clipy-history/'."""
        from clipy.hotkeys import _path_for
        path = _path_for("history")
        self.assertTrue(path.endswith("clipy-history/"))

    def test_path_for_all_actions(self):
        """All three actions produce distinct paths."""
        from clipy.hotkeys import _path_for
        paths = [_path_for(a) for a in ("history", "snippets", "menu")]
        self.assertEqual(len(paths), len(set(paths)))


class PasteModuleTest(unittest.TestCase):
    """Paste helper tests that mock subprocess and shutil."""

    def test_ydotool_not_found_returns_false(self):
        """When ydotool is not on PATH, _ydotool() returns False."""
        from unittest.mock import patch
        from clipy.paste import _ydotool
        with patch("clipy.paste.shutil.which", return_value=None):
            self.assertFalse(_ydotool())

    def test_ydotool_found_but_fails_returns_false(self):
        """When ydotool is found but subprocess.run raises CalledProcessError, returns False."""
        import subprocess
        from unittest.mock import patch
        from clipy.paste import _ydotool
        with patch("clipy.paste.shutil.which", return_value="/usr/bin/ydotool"), \
             patch("clipy.paste.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "ydotool")):
            self.assertFalse(_ydotool())
