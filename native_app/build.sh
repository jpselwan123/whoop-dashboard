#!/bin/bash
# Builds WHOOP Dashboard.app from source. Run from anywhere — paths are
# resolved relative to this script's own location, not the working directory.
set -e
cd "$(dirname "$0")"

APP="build/WHOOP Dashboard.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "Compiling..."
swiftc -O main.swift -o "$APP/Contents/MacOS/WHOOP Dashboard"
cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>WHOOP Dashboard</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>com.whoopdashboard.app</string>
  <key>CFBundleName</key>
  <string>WHOOP Dashboard</string>
  <key>CFBundleDisplayName</key>
  <string>WHOOP Dashboard</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
  </dict>
</dict>
</plist>
EOF

echo "Built: $(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"
echo "Move it to /Applications (or your Desktop) and launch it."
echo "First launch: right-click it and choose Open, since it isn't signed by an Apple-registered developer — macOS will ask you to confirm once."
