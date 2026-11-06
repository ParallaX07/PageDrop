"""Bundled logo: SVG master rendered at exact physical sizes."""

from __future__ import annotations

from pagedrop.assets import _ICON_SIZES, app_icon, logo_path, logo_pixmap

ACCENT = (0xC4, 0x50, 0x1F)


def _has_accent(pixmap, tolerance: int = 24) -> bool:
    image = pixmap.toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            rgb = (c.red(), c.green(), c.blue())
            if c.alpha() > 200 and max(abs(a - b) for a, b in zip(rgb, ACCENT, strict=True)) <= tolerance:
                return True
    return False


def test_logo_path_is_existing_svg():
    path = logo_path()
    assert path.suffix == ".svg"
    assert path.is_file()


def test_logo_pixmap_renders_exact_physical_size_and_dpr(qapp):
    pixmap = logo_pixmap(logical_size=64, device_pixel_ratio=2.0)
    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (128, 128)
    assert pixmap.devicePixelRatio() == 2.0


def test_logo_pixmap_has_accent_and_transparent_corners(qapp):
    pixmap = logo_pixmap(logical_size=128)
    assert _has_accent(pixmap)
    image = pixmap.toImage()
    for x, y in ((0, 0), (127, 0), (0, 127), (127, 127)):
        assert image.pixelColor(x, y).alpha() == 0


def test_app_icon_exposes_expected_sizes(qapp):
    icon = app_icon()
    assert not icon.isNull()
    sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
    assert sizes == {(n, n) for n in _ICON_SIZES}
