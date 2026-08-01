"""Optional tessdata language pack helpers (Phase 29).

PyMuPDF's built-in OCR needs ``*.traineddata`` files — not a separate
Tesseract executable as the primary path. An optional small ``eng`` pack may
live next to the app or in the user data directory; never required at startup.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# tessdata_fast eng — small enough for an optional download (~4 MB).
ENG_FAST_URL = (
    "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata"
)
# SHA256 of tessdata_fast eng.traineddata at ENG_FAST_URL (pinned for WC3).
ENG_FAST_SHA256 = (
    "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
)
ENG_LANG = "eng"


def user_tessdata_dir() -> Path:
    """Per-user PageDrop tessdata directory (may be empty / missing)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "PageDrop" / "tessdata"


def bundled_tessdata_dir() -> Path | None:
    """Optional shipped pack beside the package (or frozen ``_MEIPASS``).

    Returns the directory when it exists (even if empty); callers still need
    ``*.traineddata`` files for the capability to report available.
    """
    package_data = Path(__file__).resolve().parent.parent / "data" / "tessdata"
    candidates = [package_data]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "pagedrop" / "data" / "tessdata")
        candidates.append(Path(meipass) / "data" / "tessdata")
    for path in candidates:
        if path.is_dir():
            return path
    return None


def ensure_user_tessdata_dir() -> Path:
    """Create the user tessdata directory if needed; return it."""
    path = user_tessdata_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def eng_traineddata_path(directory: Path | None = None) -> Path:
    """Path where ``eng.traineddata`` is expected under *directory*."""
    return (directory or user_tessdata_dir()) / f"{ENG_LANG}.traineddata"


def download_eng_fast(
    *,
    dest_dir: Path | None = None,
    url: str = ENG_FAST_URL,
    timeout: float = 120.0,
) -> Path:
    """Download tessdata_fast ``eng.traineddata`` into *dest_dir*.

    Explicit user action only — never called at first launch. Writes via a
    temporary sibling then renames. Verifies SHA256 before replace; fails
    closed on mismatch. Returns the final ``.traineddata`` path.
    """
    directory = dest_dir or ensure_user_tessdata_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = eng_traineddata_path(directory)
    staging = target.with_suffix(".traineddata.partial")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            staging.write_bytes(response.read())
        digest = hashlib.sha256(staging.read_bytes()).hexdigest()
        if digest != ENG_FAST_SHA256:
            staging.unlink(missing_ok=True)
            raise RuntimeError(
                f"eng tessdata hash mismatch (got {digest}, "
                f"expected {ENG_FAST_SHA256})"
            )
        staging.replace(target)
    except urllib.error.URLError as exc:
        staging.unlink(missing_ok=True)
        raise RuntimeError(f"Could not download eng tessdata: {exc}") from exc
    except OSError as exc:
        staging.unlink(missing_ok=True)
        raise RuntimeError(f"Could not save eng tessdata: {exc}") from exc
    return target
