#!/usr/bin/env bash
# Build PageDrop and smoke-test the executable (Linux/macOS).
# Usage (from project root):
#   ./scripts/smoke_exe.sh
#   ./scripts/smoke_exe.sh --skip-build

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKIP_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    -h|--help)
      echo "Usage: $0 [--skip-build]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "Building executable via pagedrop.spec..."
  (cd "$ROOT" && uv run pyinstaller --noconfirm pagedrop.spec)
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  EXE="$ROOT/dist/pagedrop"
else
  EXE="$ROOT/dist/pagedrop"
fi

if [[ ! -x "$EXE" && ! -f "$EXE" ]]; then
  echo "Expected executable not found: $EXE" >&2
  exit 1
fi

echo "Launching $EXE (5s alive check)..."
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
"$EXE" &
PID=$!

cleanup() {
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

sleep 5
if ! kill -0 "$PID" 2>/dev/null; then
  wait "$PID" || true
  echo "Executable exited before 5 seconds." >&2
  exit 1
fi

echo "OK: process stayed alive for 5 seconds."
echo ""
echo "Manual verification (clean machine without Python):"
echo "  1. Copy dist/pagedrop to a system without Python."
echo "  2. Open a PDF via File -> Open PDF."
echo "  3. Drag a page thumbnail into the file manager and confirm a file is created."
echo ""
echo "Run pytest smoke test:"
echo "  PAGEDROP_EXE=$EXE uv run pytest tests/smoke/test_phase16_executable.py -v"
