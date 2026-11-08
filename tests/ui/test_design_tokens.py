"""Contrast guards for the colour tokens, and drift guard against DESIGN.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagedrop.ui import theme as theme_mod
from pagedrop.ui.accessibility import contrast_ratio
from pagedrop.ui.theme import DARK, LIGHT, app_stylesheet

THEMES = [pytest.param(LIGHT, id="light"), pytest.param(DARK, id="dark")]

DESIGN_MD = Path(__file__).resolve().parents[2] / "DESIGN.md"

INDEXES = (
    "index_clay",
    "index_teal",
    "index_ochre",
    "index_plum",
    "index_moss",
    "index_slate",
)
SURFACES = ("chrome", "raised", "canvas", "bar_top", "bar_tabs", "ink_tint")

# (foreground token, background token, minimum ratio)
TEXT_PAIRS = [
    (fg, bg, 4.5)
    for fg in ("text", "text_muted")
    for bg in ("chrome", "raised", "canvas")
]
TEXT_PAIRS += [
    (fg, bg, 4.5) for fg in ("on_bar", "on_bar_muted") for bg in ("bar_top", "bar_tabs")
]
TEXT_PAIRS += [
    (fg, bg, 4.5) for fg in ("success", "warning", "danger") for bg in SURFACES
]
MARK_PAIRS = [
    (fg, bg, 3.0) for fg in ("ink", "line_strong") for bg in ("chrome", "raised", "canvas")
]
MARK_PAIRS += [(fg, bg, 3.0) for fg in INDEXES for bg in ("bar_tabs", "raised")]
FOCUS_PAIRS = [("focus", bg, 3.0) for bg in SURFACES]
ON_FILL_PAIRS = [("on_ink", bg, 4.5) for bg in ("ink", "ink_hover", "ink_pressed")]
ON_FILL_PAIRS += [("on_index", bg, 4.5) for bg in INDEXES]

ALL_PAIRS = TEXT_PAIRS + MARK_PAIRS + FOCUS_PAIRS + ON_FILL_PAIRS


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize(
    ("fg", "bg", "minimum"), ALL_PAIRS, ids=[f"{fg}-on-{bg}" for fg, bg, _ in ALL_PAIRS]
)
def test_token_pair_meets_contrast(theme, fg, bg, minimum):
    ratio = contrast_ratio(getattr(theme, fg), getattr(theme, bg))
    assert ratio >= minimum, f"{fg} on {bg} is {ratio:.2f}:1, needs {minimum}:1"


@pytest.mark.parametrize("theme", THEMES)
def test_high_contrast_text_reaches_seven_to_one(theme):
    for bg in ("chrome", "raised", "canvas", "bar_top", "bar_tabs"):
        ratio = contrast_ratio(theme.text, getattr(theme, bg))
        assert ratio >= 7.0, f"text on {bg} is {ratio:.2f}:1, needs 7:1"


@pytest.mark.parametrize(
    ("theme", "light"), [pytest.param(LIGHT, True, id="light"), pytest.param(DARK, False, id="dark")]
)
def test_high_contrast_sheet_promotes_muted_text(theme, light):
    normal = app_stylesheet(light=light)
    high = app_stylesheet(high_contrast=True, light=light)
    for name in ("text_muted", "on_bar_muted"):
        value = getattr(theme, name)
        assert value in normal, f"{name} is no longer used by the normal sheet"
        assert value not in high, f"{name} still appears in the high-contrast sheet"


def _design_colors() -> dict[str, str]:
    colors: dict[str, str] = {}
    in_block = False
    for line in DESIGN_MD.read_text(encoding="utf-8").splitlines():
        if line.strip() == "colors:":
            in_block = True
            continue
        if in_block:
            if not line.startswith("  "):
                break
            key, _, value = line.strip().partition(":")
            colors[key] = value.strip().strip('"')
    return colors


@pytest.mark.skipif(
    not DESIGN_MD.is_file(), reason="DESIGN.md is a local-only file and is not present"
)
def test_design_md_colours_match_the_themes():
    colors = _design_colors()
    assert len(colors) > 50  # the parse found the block
    for key, value in colors.items():
        if key == "page":
            actual = {theme_mod.SURFACE_PAPER}
        elif key == "page-ink":
            actual = {theme_mod.PAGE_INK}
        else:
            dark = key.endswith("-dark")
            name = key.removesuffix("-dark").replace("-", "_")
            theme = DARK if dark else LIGHT
            assert hasattr(theme, name), f"DESIGN.md colour {key} is missing from Theme"
            actual = {getattr(theme, name)}
        assert {value.upper()} == {a.upper() for a in actual}, f"{key} drifted from DESIGN.md"
    # Every Theme field is documented, in both themes.
    for name in LIGHT.__dataclass_fields__:
        key = name.replace("_", "-")
        assert key in colors, f"{key} missing from DESIGN.md"
        assert f"{key}-dark" in colors, f"{key}-dark missing from DESIGN.md"
