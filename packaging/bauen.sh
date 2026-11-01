#!/bin/sh
# Baut die Mac-App und legt DMG und ZIP in dist/ ab.
# Aufruf: packaging/bauen.sh arm64   (oder intel)
set -e
cd "$(dirname "$0")/.."
ARCH=${1:-arm64}
PYTHON=${PYTHON:-.venv/bin/python}
rm -rf build dist
"$PYTHON" -m PyInstaller --noconfirm --clean --log-level WARN packaging/Lichtsteuerung.spec
APP=dist/Lichtsteuerung.app
# Ohne Apple-Entwicklerkonto: Ad-hoc-Signatur. Apple-Silicon-Macs verlangen sie.
codesign --force --deep -s - "$APP"
codesign --verify --deep "$APP"
plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'
LICHT_DATEN="$(mktemp -d)" "$APP/Contents/MacOS/Lichtsteuerung" --selbsttest --port 8391
ditto -c -k --keepParent "$APP" "dist/Lichtsteuerung-$ARCH.zip"
mkdir dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Programme
hdiutil create -quiet -volname Lichtsteuerung -srcfolder dist/dmg -format UDZO "dist/Lichtsteuerung-$ARCH.dmg"
rm -rf dist/dmg
ls -la dist/*.zip dist/*.dmg
