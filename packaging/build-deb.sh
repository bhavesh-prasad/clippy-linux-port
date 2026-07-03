#!/usr/bin/env bash
# Build clipy_<version>_all.deb from this source tree.
#
# Pure-Python arch:all package, so no compiler/fakeroot/dpkg-shlibdeps needed.
# `dpkg-deb --root-owner-group` writes root:root ownership without fakeroot.
#
# Usage: packaging/build-deb.sh [output_dir]
set -euo pipefail

HERE="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT="$(cd -P "$HERE/.." >/dev/null 2>&1 && pwd)"
OUT_DIR="${1:-$ROOT/dist}"

VERSION="$(awk 'NR==1{gsub(/[()]/,""); print $2; exit}' "$HERE/changelog")"
PKG="clipy"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo ">> building $PKG $VERSION"

# --- filesystem layout ------------------------------------------------------
install -d "$STAGE/DEBIAN"
install -d "$STAGE/usr/bin"
install -d "$STAGE/usr/share/clipy/clipy"
install -d "$STAGE/usr/share/applications"
install -d "$STAGE/usr/share/icons/hicolor/scalable/apps"
install -d "$STAGE/usr/share/doc/clipy"

# Python package (source of truth: repo's clipy/, minus caches)
cp -r "$ROOT/clipy/." "$STAGE/usr/share/clipy/clipy/"
find "$STAGE/usr/share/clipy" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE/usr/share/clipy" -name '*.pyc' -delete

# Launcher
install -m 0755 "$HERE/clipy" "$STAGE/usr/bin/clipy"

# Desktop entry + icon
install -m 0644 "$HERE/clipy.desktop" "$STAGE/usr/share/applications/clipy.desktop"
install -m 0644 "$ROOT/data/icons/clipy.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/clipy.svg"

# Docs
install -m 0644 "$ROOT/README.md" "$STAGE/usr/share/doc/clipy/README.md"
install -m 0644 "$HERE/copyright" "$STAGE/usr/share/doc/clipy/copyright"
gzip -9 -n -c "$HERE/changelog" > "$STAGE/usr/share/doc/clipy/changelog.gz"
chmod 0644 "$STAGE/usr/share/doc/clipy/changelog.gz"

# Normalise permissions (mktemp gives the root 0700; source files may be 0664).
chmod 0755 "$STAGE"
find "$STAGE/usr" -type d -exec chmod 0755 {} +
find "$STAGE/usr/share/clipy" "$STAGE/usr/share/applications" \
     "$STAGE/usr/share/icons" "$STAGE/usr/share/doc" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/usr/bin/clipy"

# --- control files ----------------------------------------------------------
INSTALLED_KB="$(du -sk "$STAGE/usr" | cut -f1)"
sed "s/^Version: .*/Version: $VERSION/" "$HERE/control" > "$STAGE/DEBIAN/control"
printf 'Installed-Size: %s\n' "$INSTALLED_KB" >> "$STAGE/DEBIAN/control"

install -m 0755 "$HERE/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$HERE/postrm" "$STAGE/DEBIAN/postrm"

# conffiles: none (we ship no /etc config)

# --- build ------------------------------------------------------------------
mkdir -p "$OUT_DIR"
DEB="$OUT_DIR/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB"

echo ">> built $DEB"
