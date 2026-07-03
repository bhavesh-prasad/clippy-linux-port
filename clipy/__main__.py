"""Entry point: ``python3 -m clipy [--action history|snippets|menu|preferences|quit]``.

Forces the X11 (XWayland) GDK backend so clipboard monitoring works without focus on
GNOME Wayland (see the design doc), then runs the single-instance application.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

# Must be set before GDK/GTK is imported anywhere.
os.environ.setdefault("GDK_BACKEND", "x11")


def _launcher_command() -> str:
    """Command GNOME shortcuts run to reach this app. Prefer the bin/ launcher."""
    override = os.environ.get("CLIPY_LAUNCHER")
    if override:
        return override
    project_root = Path(__file__).resolve().parent.parent
    launcher = project_root / "bin" / "clipy-linux"
    if launcher.exists():
        return shlex.quote(str(launcher))
    # Fallback: re-run this module with the same interpreter and source path.
    return (f"env PYTHONPATH={shlex.quote(str(project_root))} "
            f"GDK_BACKEND=x11 {shlex.quote(sys.executable)} -m clipy")


def main() -> int:
    from .app import ClipyApplication
    app = ClipyApplication(_launcher_command())
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
