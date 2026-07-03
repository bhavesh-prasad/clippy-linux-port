"""SQLite persistence for clipboard history and snippets.

A single database file holds both. All access goes through :class:`Store`, which is
safe to use from the GTK main thread (SQLite in-process, short transactions).
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from . import config
from .models import HistoryItem, Snippet, SnippetFolder

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    image_path TEXT,
    source_app TEXT,
    hash       TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at DESC);

CREATE TABLE IF NOT EXISTS folders (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    ordering INTEGER NOT NULL DEFAULT 0,
    enabled  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS snippets (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    title     TEXT NOT NULL,
    content   TEXT NOT NULL DEFAULT '',
    ordering  INTEGER NOT NULL DEFAULT 0,
    enabled   INTEGER NOT NULL DEFAULT 1
);
"""


def content_hash(kind: str, text: str, image_bytes: bytes | None) -> str:
    h = hashlib.sha256()
    h.update(kind.encode())
    h.update(b"\0")
    if kind == "image" and image_bytes is not None:
        h.update(image_bytes)
    else:
        h.update(text.encode())
    return h.hexdigest()


class Store:
    def __init__(self, path: Path | None = None):
        config.ensure_dirs()
        self.path = path or config.DB_PATH
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- history -------------------------------------------------------
    def _row_to_item(self, r: sqlite3.Row) -> HistoryItem:
        return HistoryItem(
            id=r["id"], kind=r["kind"], text=r["text"], image_path=r["image_path"],
            source_app=r["source_app"], hash=r["hash"], created_at=r["created_at"],
        )

    def latest_hash(self) -> str | None:
        r = self.conn.execute(
            "SELECT hash FROM history ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return r["hash"] if r else None

    def add_text(self, text: str, source_app: str | None = None) -> HistoryItem | None:
        return self._add("text", text, None, source_app)

    def add_image(self, image_bytes: bytes, source_app: str | None = None) -> HistoryItem | None:
        digest = content_hash("image", "", image_bytes)
        if self.latest_hash() == digest:
            return None
        path = config.IMAGE_CACHE_DIR / f"{digest[:16]}.png"
        if not path.exists():
            path.write_bytes(image_bytes)
        return self._insert("image", "", str(path), source_app, digest)

    def _add(self, kind: str, text: str, image_path: str | None,
             source_app: str | None) -> HistoryItem | None:
        digest = content_hash(kind, text, None)
        if self.latest_hash() == digest:
            return None
        return self._insert(kind, text, image_path, source_app, digest)

    def _insert(self, kind, text, image_path, source_app, digest) -> HistoryItem:
        # If this content already exists elsewhere, move it to the top instead of
        # creating a duplicate (Clipy behaviour).
        self.conn.execute("DELETE FROM history WHERE hash = ?", (digest,))
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO history(kind, text, image_path, source_app, hash, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (kind, text, image_path, source_app, digest, now),
        )
        self.conn.commit()
        return HistoryItem(cur.lastrowid, kind, text, image_path, source_app, digest, now)

    def history(self, limit: int | None = None) -> list[HistoryItem]:
        sql = "SELECT * FROM history ORDER BY created_at DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [self._row_to_item(r) for r in self.conn.execute(sql).fetchall()]

    def get_history(self, item_id: int) -> HistoryItem | None:
        r = self.conn.execute("SELECT * FROM history WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_item(r) if r else None

    def delete_history(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM history WHERE id = ?", (item_id,))
        self.conn.commit()

    def clear_history(self) -> None:
        self.conn.execute("DELETE FROM history")
        self.conn.commit()

    def trim_history(self, max_items: int) -> None:
        self.conn.execute(
            "DELETE FROM history WHERE id NOT IN ("
            "  SELECT id FROM history ORDER BY created_at DESC LIMIT ?)",
            (max_items,),
        )
        self.conn.commit()

    # ---- snippets ------------------------------------------------------
    def folders(self) -> list[SnippetFolder]:
        rows = self.conn.execute(
            "SELECT * FROM folders ORDER BY ordering, id"
        ).fetchall()
        return [SnippetFolder(r["id"], r["name"], r["ordering"], bool(r["enabled"]))
                for r in rows]

    def add_folder(self, name: str) -> SnippetFolder:
        ordering = (self.conn.execute("SELECT COALESCE(MAX(ordering),-1)+1 FROM folders")
                    .fetchone()[0])
        cur = self.conn.execute(
            "INSERT INTO folders(name, ordering, enabled) VALUES (?,?,1)",
            (name, ordering),
        )
        self.conn.commit()
        return SnippetFolder(cur.lastrowid, name, ordering, True)

    def rename_folder(self, folder_id: int, name: str) -> None:
        self.conn.execute("UPDATE folders SET name=? WHERE id=?", (name, folder_id))
        self.conn.commit()

    def set_folder_enabled(self, folder_id: int, enabled: bool) -> None:
        self.conn.execute("UPDATE folders SET enabled=? WHERE id=?",
                          (int(enabled), folder_id))
        self.conn.commit()

    def delete_folder(self, folder_id: int) -> None:
        self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self.conn.commit()

    def snippets(self, folder_id: int | None = None) -> list[Snippet]:
        if folder_id is None:
            rows = self.conn.execute(
                "SELECT * FROM snippets ORDER BY folder_id, ordering, id").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM snippets WHERE folder_id=? ORDER BY ordering, id",
                (folder_id,)).fetchall()
        return [Snippet(r["id"], r["folder_id"], r["title"], r["content"],
                        r["ordering"], bool(r["enabled"])) for r in rows]

    def get_snippet(self, snippet_id: int) -> Snippet | None:
        r = self.conn.execute("SELECT * FROM snippets WHERE id=?", (snippet_id,)).fetchone()
        if not r:
            return None
        return Snippet(r["id"], r["folder_id"], r["title"], r["content"],
                       r["ordering"], bool(r["enabled"]))

    def add_snippet(self, folder_id: int, title: str, content: str = "") -> Snippet:
        ordering = (self.conn.execute(
            "SELECT COALESCE(MAX(ordering),-1)+1 FROM snippets WHERE folder_id=?",
            (folder_id,)).fetchone()[0])
        cur = self.conn.execute(
            "INSERT INTO snippets(folder_id, title, content, ordering, enabled)"
            " VALUES (?,?,?,?,1)", (folder_id, title, content, ordering))
        self.conn.commit()
        return Snippet(cur.lastrowid, folder_id, title, content, ordering, True)

    def update_snippet(self, snippet_id: int, title: str, content: str) -> None:
        self.conn.execute("UPDATE snippets SET title=?, content=? WHERE id=?",
                          (title, content, snippet_id))
        self.conn.commit()

    def set_snippet_enabled(self, snippet_id: int, enabled: bool) -> None:
        self.conn.execute("UPDATE snippets SET enabled=? WHERE id=?",
                          (int(enabled), snippet_id))
        self.conn.commit()

    def delete_snippet(self, snippet_id: int) -> None:
        self.conn.execute("DELETE FROM snippets WHERE id=?", (snippet_id,))
        self.conn.commit()

    def seed_default_snippets(self) -> None:
        """Create a sample folder on first run, like Clipy ships with."""
        if self.folders():
            return
        f = self.add_folder("Sample")
        self.add_snippet(f.id, "Email", "hello@example.com")
        self.add_snippet(f.id, "Shrug", "¯\\_(ツ)_/¯")
