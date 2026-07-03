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


if __name__ == "__main__":
    unittest.main()
