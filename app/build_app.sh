#!/bin/bash
# Build "文章转卡片.app" into <project>/dist/.
#
# Usage: ./app/build_app.sh
# Requires: macOS, uv (for Pillow + a Python with Tk 9), iconutil, sips.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$APP_DIR/.." && pwd)"
DIST="$ROOT/dist"
NAME="文章转卡片"
BUNDLE="$DIST/$NAME.app"

echo "==> project: $ROOT"
echo "==> output:  $BUNDLE"

if [ ! -f "$ROOT/skills/make-knowledge-cards/SKILL.md" ]; then
  echo "error: SKILL.md not found under $ROOT" >&2
  exit 1
fi

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

echo "==> generating icon"
uv run --with pillow python "$APP_DIR/icon.py" "$APP_DIR/icon.png"

ICONSET="$APP_DIR/icon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$APP_DIR/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z "$((s * 2))" "$((s * 2))" "$APP_DIR/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUNDLE/Contents/Resources/icon.icns"
rm -rf "$ICONSET"

echo "==> copying app files"
cp "$APP_DIR/card_app.py" "$BUNDLE/Contents/Resources/card_app.py"
cat > "$BUNDLE/Contents/Resources/config.json" <<EOF
{
  "project_dir": "$ROOT"
}
EOF

echo "==> writing Info.plist"
cat > "$BUNDLE/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>文章转卡片</string>
    <key>CFBundleDisplayName</key>
    <string>文章转卡片</string>
    <key>CFBundleIdentifier</key>
    <string>com.makeknowledgecards.app</string>
    <key>CFBundleVersion</key>
    <string>0.2.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.2.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.productivity</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

echo "==> writing launcher"
cat > "$BUNDLE/Contents/MacOS/launcher" <<'EOF'
#!/bin/zsh
export PATH="$HOME/.local/bin:$HOME/.opencode/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="${LANG:-en_US.UTF-8}"

DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"

PY=""
if command -v uv >/dev/null 2>&1; then
  for v in 3.15 3.14 3.13 3.12 3.11 3.10; do
    CANDIDATE="$(uv python find "$v" 2>/dev/null || true)"
    if [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ]; then
      PY="$CANDIDATE"
      break
    fi
  done
fi

if [ -z "$PY" ] || ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  PY="/usr/bin/python3"
fi

exec "$PY" "$DIR/card_app.py"
EOF
chmod +x "$BUNDLE/Contents/MacOS/launcher"

echo "==> ad-hoc signing"
codesign --force --deep --sign - "$BUNDLE" >/dev/null 2>&1 || true

echo "==> done"
echo "    $BUNDLE"
du -sh "$BUNDLE"
