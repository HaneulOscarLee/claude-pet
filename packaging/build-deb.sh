#!/usr/bin/env bash
# Build claude-pet_<version>_all.deb into dist/.
#
#   packaging/build-deb.sh [revision]
#
# Pure Python and data files, so the package is Architecture: all and needs no
# compilation. apt resolves GTK, Pillow and wmctrl from Depends, which is the
# point of shipping a .deb at all: installing it needs no terminal.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
REVISION="${1:-1}"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/claude_pet/__init__.py")"
[ -n "$VERSION" ] || { echo "build-deb: no __version__ in claude_pet/__init__.py" >&2; exit 1; }

PACKAGE="claude-pet"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

INSTALL_DIR="$STAGE/usr/lib/$PACKAGE"
mkdir -p "$INSTALL_DIR" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/bash-completion/completions" \
         "$STAGE/usr/share/doc/$PACKAGE" \
         "$STAGE/DEBIAN"

# Only what the program needs at runtime.
cp -r "$ROOT/claude_pet" "$ROOT/assets" "$ROOT/completions" "$ROOT/claude-pet" "$INSTALL_DIR/"
find "$INSTALL_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
chmod 755 "$INSTALL_DIR/claude-pet"

ln -s "/usr/lib/$PACKAGE/claude-pet" "$STAGE/usr/bin/claude-pet"
cp "$HERE/claude-pet.desktop" "$STAGE/usr/share/applications/"
ln -s "/usr/lib/$PACKAGE/completions/claude-pet.bash" \
      "$STAGE/usr/share/bash-completion/completions/claude-pet"
cp "$ROOT/README.md" "$ROOT/LICENSE" "$STAGE/usr/share/doc/$PACKAGE/"

# The pet is drawn from the bundled pack, which doubles as the app icon.
if [ -f "$ROOT/assets/pets/pocket/spritesheet.webp" ] && command -v python3 >/dev/null; then
    mkdir -p "$STAGE/usr/share/icons/hicolor/128x128/apps"
    python3 - "$ROOT/assets/pets/pocket/spritesheet.webp" \
              "$STAGE/usr/share/icons/hicolor/128x128/apps/claude-pet.png" <<'PY'
import sys
from PIL import Image

source, target = sys.argv[1], sys.argv[2]
with Image.open(source) as sheet:
    # First cell of the idle row, trimmed to the drawn pixels.
    cell = sheet.convert("RGBA").crop((0, 0, 192, 208))
box = cell.getchannel("A").getbbox()
if box:
    cell = cell.crop(box)
side = max(cell.size)
icon = Image.new("RGBA", (side, side), (0, 0, 0, 0))
icon.alpha_composite(cell, ((side - cell.width) // 2, (side - cell.height) // 2))
icon.resize((128, 128), Image.NEAREST).save(target)
PY
fi

# Stamp the version so an installed package can say what it is. Without this
# `update --check` has nothing to compare and reports an update every time.
printf '%s\n' "$VERSION" > "$INSTALL_DIR/.claude-pet-version"

INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION-$REVISION
Section: utils
Priority: optional
Architecture: all
Maintainer: haneullee <noreply@users.noreply.github.com>
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, python3-pil
Recommends: wmctrl, libnotify-bin
Suggests: tmux
Homepage: https://github.com/HaneulOscarLee/claude-pet
Description: Desktop pet that shows what Claude Code is doing
 An always-on-top sprite that reacts to Claude Code's session state -- working,
 blocked on you, finished, or failed -- so you can tell at a glance without
 switching to the terminal.
 .
 It renders sprite packs from codex-pets.net, the same packs the Codex desktop
 app uses. Clicking the pet jumps to the session that wants attention.
 .
 Launch "claude-pet" once from your applications menu to finish setup: it
 installs a sprite pack, wires the Claude Code hooks into your own
 ~/.claude/settings.json, and starts the pet.
EOF

# Nothing per-user happens here on purpose: postinst runs as root, and the hooks
# and config belong to whoever is logged in. `claude-pet start` does that, and
# the desktop entry runs it.
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
    fi
fi
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
# Leave the user's packs, config and hooks alone; only stop a running pet.
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/prerm"

# Normalise permissions: the working tree is group-writable, packages are not.
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f ! -path '*/DEBIAN/*' -exec chmod 644 {} +
chmod 755 "$INSTALL_DIR/claude-pet"
mkdir -p "$ROOT/dist"
OUTPUT="$ROOT/dist/${PACKAGE}_${VERSION}-${REVISION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUTPUT" >/dev/null
echo "$OUTPUT"
