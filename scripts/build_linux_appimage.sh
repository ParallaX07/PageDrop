#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cd "$ROOT" && uv run --locked python scripts/read_version.py)"
APPIMAGE_NAME="PageDrop-${VERSION}-x86_64.AppImage"
TOOL="${RUNNER_TEMP:-/tmp}/appimagetool-x86_64.AppImage"
RUNTIME="${RUNNER_TEMP:-/tmp}/runtime-x86_64"
APPDIR="$ROOT/dist/PageDrop.AppDir"

fetch_verified() {
  local url="$1" sha="$2" output="$3"
  curl --fail --location --silent --show-error "$url" --output "$output"
  echo "$sha  $output" | sha256sum --check --status || {
    echo "SHA-256 verification failed for $output" >&2
    exit 1
  }
}

fetch_verified \
  https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
  ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0 "$TOOL"
fetch_verified \
  https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
  2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d "$RUNTIME"
chmod +x "$TOOL" "$RUNTIME"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
  "$APPDIR/usr/share/licenses/pagedrop" "$APPDIR/usr/share/metainfo" \
  "$APPDIR/usr/share/applications"
cp -a "$ROOT/dist/pagedrop/." "$APPDIR/usr/bin/"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$APPDIR/usr/share/licenses/pagedrop/"
cp "$ROOT/src/pagedrop/assets/logo.png" "$APPDIR/pagedrop.png"
cp "$ROOT/src/pagedrop/assets/logo.png" "$APPDIR/.DirIcon"
cp "$ROOT/src/pagedrop/assets/logo.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/pagedrop.png"
cp "$ROOT/src/pagedrop/assets/io.github.ParallaX07.PageDrop.appdata.xml" "$APPDIR/usr/share/metainfo/"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/pagedrop" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"
cat > "$APPDIR/io.github.ParallaX07.PageDrop.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=PageDrop
Comment=Organize and edit PDF pages
Exec=pagedrop %F
Icon=pagedrop
Categories=Office;
Terminal=false
MimeType=application/pdf;
DESKTOP
cp "$APPDIR/io.github.ParallaX07.PageDrop.desktop" "$APPDIR/usr/share/applications/"

cd "$ROOT/dist"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run \
  --runtime-file "$RUNTIME" \
  --updateinformation 'gh-releases-zsync|ParallaX07|PageDrop|latest|PageDrop-*-x86_64.AppImage.zsync' \
  "$APPDIR" "$APPIMAGE_NAME"
test -s "$APPIMAGE_NAME"
test -s "$APPIMAGE_NAME.zsync"
sha256sum "$APPIMAGE_NAME" > "$APPIMAGE_NAME.sha256"
chmod +x "$APPIMAGE_NAME"
echo "Built $ROOT/dist/$APPIMAGE_NAME"
