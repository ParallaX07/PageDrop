"""Capture offscreen screenshots of key screens in both themes.

Usage:
  uv run python scripts/capture_ui.py                  # build/ui-shots/current/
  uv run python scripts/capture_ui.py --label before   # build/ui-shots/before/

Writes ``{light,dark}-{empty,grid,tools,merge,preferences}.png``. Settings are
routed to a temp ini file, so real user preferences are never touched.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PAGEDROP_TESTING"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.fixtures.generate_fixtures import ensure_fixtures, fixture_path  # noqa: E402

SIZE = (1280, 800)
THEMES = ("light", "dark")
LOAD_TIMEOUT_S = 20.0


def _set_theme(theme: str) -> None:
    """Apply a theme; the only place that knows the appearance setting API."""
    from pagedrop.ui import settings
    from pagedrop.ui.accessibility import refresh_themed_widgets

    settings.set_light_theme(theme == "light")
    refresh_themed_widgets(QApplication.instance())


def _pump(seconds: float = 0.0) -> None:
    app = QApplication.instance()
    end = time.monotonic() + seconds
    app.processEvents()
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def _wait_loaded(win) -> None:
    deadline = time.monotonic() + LOAD_TIMEOUT_S
    while time.monotonic() < deadline:
        _pump()
        if (
            win._loader is not None
            and not win._progress_bar.isVisible()
            and "Loaded" in win.statusBar().currentMessage()
            and len(win._thumbnail_grid._cards) == win._loader.page_count
        ):
            return
        time.sleep(0.02)
    raise RuntimeError("timed out waiting for the PDF to load")


def _save(widget, path: Path) -> None:
    widget.resize(*SIZE)
    widget.show()
    _pump(0.3)
    image = widget.grab()
    if image.isNull() or not image.save(str(path)) or not path.is_file():
        raise RuntimeError(f"could not save {path}")


def _main_window_shots(out: Path, theme: str, pdf: Path) -> None:
    from pagedrop.ui.main_window import MainWindow

    def shot(name: str, prepare=None) -> None:
        win = MainWindow()
        try:
            if prepare is not None:
                prepare(win)
            _save(win, out / f"{theme}-{name}.png")
        except Exception as exc:
            raise RuntimeError(f"{theme}-{name}: {exc}") from exc
        finally:
            win.close()
            win._temp_manager.cleanup()
            win.deleteLater()
            _pump()

    def open_pdf(win) -> None:
        win.open_command_line_paths([str(pdf)])
        _wait_loaded(win)

    def tools(win) -> None:
        open_pdf(win)
        win._open_tools_window()

    def merge(win) -> None:
        open_pdf(win)
        win._open_merge_window()

    shot("empty")
    shot("grid", open_pdf)
    shot("tools", tools)
    shot("merge", merge)


def _preferences_shot(out: Path, theme: str) -> None:
    from pagedrop.ui.preferences_dialog import PreferencesDialog

    dialog = PreferencesDialog()
    try:
        _save(dialog, out / f"{theme}-preferences.png")
    except Exception as exc:
        raise RuntimeError(f"{theme}-preferences: {exc}") from exc
    finally:
        dialog.close()
        dialog.deleteLater()
        _pump()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="current", help="output subfolder name")
    args = parser.parse_args()
    out = ROOT / "build" / "ui-shots" / args.label
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pagedrop_shots_") as tmp:
        tmp_dir = Path(tmp)
        ini = tmp_dir / "settings.ini"

        from pagedrop.ui import settings

        settings._settings = lambda: QSettings(str(ini), QSettings.Format.IniFormat)

        from pagedrop.ui.accessibility import install_accessibility

        app = QApplication(sys.argv[:1])
        app.setOrganizationName("PageDrop")
        app.setApplicationName("PageDrop")
        app.setQuitOnLastWindowClosed(False)
        app.setStyle("Fusion")
        install_accessibility(app)
        settings.set_reduce_motion(True)

        fixtures = tmp_dir / "fixtures"
        ensure_fixtures(fixtures)
        pdf = fixture_path(fixtures, "five_page")

        try:
            for theme in THEMES:
                _set_theme(theme)
                _main_window_shots(out, theme, pdf)
                _preferences_shot(out, theme)
        except RuntimeError as exc:
            print(f"capture failed: {exc}", file=sys.stderr)
            return 1

    print(f"Saved {len(list(out.glob('*.png')))} screenshots to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
