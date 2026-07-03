"""Plain data models shared across storage, UI, and the tray menu."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HistoryItem:
    id: int
    kind: str  # "text" | "image"
    text: str  # display/plain text ("" for images)
    image_path: str | None  # PNG path for image items
    source_app: str | None
    hash: str
    created_at: float

    def preview(self, max_len: int = 40) -> str:
        """One-line label suitable for a menu."""
        if self.kind == "image":
            return "🖼  Image"
        s = " ".join(self.text.split())  # collapse whitespace/newlines
        if len(s) > max_len:
            s = s[: max_len - 1].rstrip() + "…"
        return s or "(empty)"


@dataclass
class SnippetFolder:
    id: int
    name: str
    ordering: int
    enabled: bool


@dataclass
class Snippet:
    id: int
    folder_id: int
    title: str
    content: str
    ordering: int
    enabled: bool
