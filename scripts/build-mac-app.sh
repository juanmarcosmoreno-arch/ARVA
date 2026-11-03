#!/bin/sh
# Build ARVA.app, the native macOS app (apps/mac/ARVA: Swift, AppKit and WebKit, no other dependencies), and zip it.
#   scripts/build-mac-app.sh [OUTPUT_DIR]      (default: apps/mac/build)
# Produces OUTPUT_DIR/ARVA.app and OUTPUT_DIR/ARVA-mac.zip. macOS only; it needs Xcode or the Command Line Tools
# (xcode-select --install) for xcrun swiftc, and uses only tools macOS has (lipo, sips, iconutil, plutil, codesign,
# ditto, shasum). Nothing is downloaded.
#
# - The app is universal (arm64 and x86_64), for macOS 13 or later, version = ARVA's (apps/api/app/__init__.py).
# - Contents/Resources/runtime gets what the launcher needs, copied here from the repository (not kept twice in
#   git): docker-compose.yml, scripts/start.sh, stop.sh, metadata-backup.sh, diagnostics.sh, backup.sh, restore.sh,
#   scripts/lib/*.sh, the docker/ files docker-compose.yml names, import/README.md, apps/api/app/__init__.py (the
#   version start.sh uses as the image tag) and the ARVA.command pair. The app copies them into
#   ~/Library/Application Support/ARVA/runtime when they change (.arva-runtime-id, a checksum of them all).
# - The icon is drawn from apps/web/public/arva-logo.png (padded to a square, never stretched) by the app itself
#   (--render-iconset), or by sips when that fails, then made into ARVA.icns by iconutil.
# - Signed ad hoc (codesign -s -): not notarized, so the first open needs Control-click → Open or System Settings →
#   Privacy & Security → Open Anyway (docs/guia-mac-app.md).
# ARVA_BUILD_NUMBER sets CFBundleVersion (default: the number of commits).
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:-$ROOT/apps/mac/build}
SRC=$ROOT/apps/mac/ARVA

fail() {
  printf 'build-mac-app: %s\n' "$1" >&2
  exit 1
}

[ "$(uname -s)" = Darwin ] || fail "ARVA.app is built on a Mac (macOS with Xcode or the Command Line Tools)."
command -v xcrun >/dev/null 2>&1 || fail "xcrun was not found: install the Command Line Tools with xcode-select --install."
xcrun --sdk macosx --find swiftc >/dev/null 2>&1 ||
  fail "swiftc was not found: install Xcode or the Command Line Tools (xcode-select --install)."

version=$(sed -n 's/^__version__ = "\([0-9a-z.]*\)".*/\1/p' "$ROOT/apps/api/app/__init__.py")
[ -n "$version" ] || fail "no __version__ in apps/api/app/__init__.py."
build=${ARVA_BUILD_NUMBER:-$(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 1)}
case "$build" in '' | *[!0-9.]*) build=1 ;; esac
commit=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)
case "$commit" in '' | *[!0-9a-f]*) commit=unknown ;; esac
# Help → the guide, as it is at this commit (a link that keeps working on GitHub whichever branch it was built from).
guide_ref=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo main)
case "$guide_ref" in '' | *[!0-9a-f]*) guide_ref=main ;; esac
guide_url=https://github.com/juanmarcosmoreno-arch/ARVA/blob/$guide_ref/docs/guia-mac-app.md

APP=$OUT/ARVA.app
WORK=$OUT/work
rm -rf "$APP" "$WORK" "$OUT/ARVA-mac.zip"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/runtime" "$WORK"
printf 'ARVA.app %s (build %s, commit %s)\n' "$version" "$build" "$commit"

# 1. The program, for each architecture, then one universal binary.
sdk=$(xcrun --sdk macosx --show-sdk-path)
for arch in arm64 x86_64; do
  printf 'Compiling for %s\n' "$arch"
  xcrun --sdk macosx swiftc -O -swift-version 5 -module-name ARVA \
    -target "$arch-apple-macos13.0" -sdk "$sdk" \
    -framework AppKit -framework WebKit -framework UniformTypeIdentifiers \
    -o "$WORK/ARVA-$arch" "$SRC"/*.swift
done
lipo -create -output "$APP/Contents/MacOS/ARVA" "$WORK/ARVA-arm64" "$WORK/ARVA-x86_64"
lipo -info "$APP/Contents/MacOS/ARVA"

# 2. Info.plist, with the version.
sed -e "s/@VERSION@/$version/g" -e "s/@BUILD@/$build/g" -e "s/@COMMIT@/$commit/g" -e "s|@GUIDE_URL@|$guide_url|g" \
  "$SRC/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

# 3. The launcher files.
RUNTIME=$APP/Contents/Resources/runtime
bundle() {
  [ -f "$ROOT/$1" ] || fail "$1 is missing from the repository."
  mkdir -p "$RUNTIME/$(dirname -- "$1")"
  cp -p "$ROOT/$1" "$RUNTIME/$1"
}
for file in docker-compose.yml scripts/start.sh scripts/stop.sh scripts/metadata-backup.sh scripts/diagnostics.sh \
  scripts/backup.sh scripts/restore.sh import/README.md apps/api/app/__init__.py ARVA.command "Detener ARVA.command" \
  docker/api.Dockerfile docker/web.Dockerfile docker/nginx.conf docker/api-entrypoint.sh; do
  bundle "$file"
done
for file in "$ROOT"/scripts/lib/*.sh; do
  bundle "scripts/lib/$(basename -- "$file")"
done
runtime_id=$(cd "$RUNTIME" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do
  printf '%s  ' "$f"
  shasum -a 256 < "$f" | cut -d ' ' -f 1
done | shasum -a 256 | cut -d ' ' -f 1)
printf '%s-%s\n' "$version" "$runtime_id" > "$RUNTIME/.arva-runtime-id"
printf 'Launcher files: %s\n' "$(cat "$RUNTIME/.arva-runtime-id")"

# 4. Resources: translations of the Info.plist texts, the logo and the icon.
cp -R "$SRC/Resources/en.lproj" "$SRC/Resources/es.lproj" "$APP/Contents/Resources/"
LOGO=$ROOT/apps/web/public/arva-logo.png
[ -f "$LOGO" ] || fail "apps/web/public/arva-logo.png is missing."
cp "$LOGO" "$APP/Contents/Resources/arva-logo.png"
ICONSET=$WORK/ARVA.iconset
host_arch=$(uname -m)
[ "$host_arch" = arm64 ] || host_arch=x86_64
if ! "$WORK/ARVA-$host_arch" --render-iconset "$LOGO" "$ICONSET"; then
  printf 'The app could not draw the icon; using sips instead.\n'
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  width=$(sips -g pixelWidth "$LOGO" | awk '/pixelWidth/ { print $2 }')
  height=$(sips -g pixelHeight "$LOGO" | awk '/pixelHeight/ { print $2 }')
  side=$width
  [ "$height" -le "$side" ] || side=$height
  sips --padToHeightWidth "$side" "$side" --padColor FFFFFF "$LOGO" --out "$WORK/square.png" >/dev/null
  for points in 16 32 128 256 512; do
    sips -z "$points" "$points" "$WORK/square.png" --out "$ICONSET/icon_${points}x${points}.png" >/dev/null
    double=$((points * 2))
    sips -z "$double" "$double" "$WORK/square.png" --out "$ICONSET/icon_${points}x${points}@2x.png" >/dev/null
  done
fi
iconutil -c icns -o "$APP/Contents/Resources/ARVA.icns" "$ICONSET"

# 5. Ad-hoc signature (Apple silicon runs only signed code) and the zip to pass on.
xattr -cr "$APP" 2>/dev/null || true
codesign --force --sign - --timestamp=none "$APP"
codesign --verify --strict --verbose=2 "$APP"
ditto -c -k --keepParent "$APP" "$OUT/ARVA-mac.zip"
rm -rf "$WORK"
printf 'Built %s and %s\n' "$APP" "$OUT/ARVA-mac.zip"
