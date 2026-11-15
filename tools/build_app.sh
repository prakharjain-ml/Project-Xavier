#!/bin/bash
# Build Xavier.app (the launcher as a real macOS app with an icon) into ~/Applications, outside the repo.
#   ./tools/build_app.sh        then open ~/Applications/Xavier.app, or drag it to the Dock
# The app runs `python -m interface.launcher` from this checkout with the project venv. Rebuild after moving the repo.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
PY="$HOME/venvs/hp26/bin/python"
APP="$HOME/Applications/Xavier.app"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 1. Icon: drawn with the app's own theme (navy squircle, cyan ring logo), then every size macOS wants.
"$PY" - "$WORK/icon_1024.png" <<'EOF'
import sys
from PIL import Image, ImageDraw, ImageFilter
from interface import theme as t

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((100, 118, 924, 942), 190, fill=(0, 0, 0, 120))
img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
body = t.canvas(824, 824).convert("RGBA")      # the app background with its top glow
mask = Image.new("L", (824, 824), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, 823, 823), 185, fill=255)
img.paste(body, (100, 100), mask)
g = ImageDraw.Draw(img)
g.rounded_rectangle((100, 100, 923, 923), 185, outline=(*t.BORDER, 255), width=4)
c, r = S / 2, 230
g.ellipse((c - r, c - r, c + r, c + r), outline=(*t.PRIMARY, 255), width=58)
d = 84
g.ellipse((c - d, c - d, c + d, c + d), fill=(*t.PRIMARY, 255))
img.save(sys.argv[1])
EOF
mkdir -p "$WORK/Xavier.iconset"
for size in 16 32 64 128 256 512; do
  sips -z $size $size "$WORK/icon_1024.png" --out "$WORK/Xavier.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z $double $double "$WORK/icon_1024.png" --out "$WORK/Xavier.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$WORK/Xavier.iconset" -o "$WORK/Xavier.icns"

# 2. Bundle: Info.plist, the icon, and a tiny launcher script.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$WORK/Xavier.icns" "$APP/Contents/Resources/Xavier.icns"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Xavier</string>
  <key>CFBundleDisplayName</key><string>Xavier</string>
  <key>CFBundleIdentifier</key><string>edu.hackprinceton.xavier</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Xavier</string>
  <key>CFBundleIconFile</key><string>Xavier</string>
  <key>NSCameraUsageDescription</key><string>Xavier uses the cameras to follow your eyes and see the room.</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
cat > "$APP/Contents/MacOS/Xavier" <<EOF
#!/bin/bash
# Xavier.app entry point: the launcher from this checkout, output kept with the session logs.
cd "$REPO" || exit 1
mkdir -p data/raw/sessions
exec "$PY" -m interface.web >> data/raw/sessions/web_stdout.log 2>&1
EOF
chmod +x "$APP/Contents/MacOS/Xavier"
touch "$APP"   # make Finder pick up the new icon
echo "Built $APP"
