"""Phase 4 unit tests — PageCard."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from pagedrop.ui.accessibility import apply_app_stylesheet
from pagedrop.ui.page_card import PageCard
from pagedrop.ui.settings import set_light_theme
from pagedrop.ui.theme import (
    DARK,
    FOCUS_WIDTH_HIGH_CONTRAST,
    LIGHT,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    PAGE_OUTLINE_WIDTH,
    PAGE_RING_GAP,
    CARD_PADDING,
    app_stylesheet,
    index_qcolor,
)

_BACKDROP = QColor("#FF00FF")
_PAGE = QColor("#00A000")


def _page(width: int, height: int) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(_PAGE)
    return pixmap


def _card_on_backdrop(qtbot, pixmap: QPixmap | None, *, thumb_width: int = 160):
    """A shown card over a magenta backdrop, so a painted fill cannot hide."""
    backdrop = QWidget()
    backdrop.setAutoFillBackground(True)
    palette = backdrop.palette()
    palette.setColor(backdrop.backgroundRole(), _BACKDROP)
    backdrop.setPalette(palette)
    layout = QVBoxLayout(backdrop)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    card = PageCard(0, backdrop)
    layout.addWidget(card)
    card.set_card_width(thumb_width + CARD_PADDING)
    if pixmap is not None:
        card.set_thumbnail(pixmap)
    qtbot.addWidget(backdrop)
    backdrop.resize(thumb_width + CARD_PADDING + 24, 400)
    backdrop.show()
    qtbot.waitExposed(backdrop)
    return backdrop, card


def _pixel(backdrop: QWidget, card: PageCard, x: int, y: int) -> QColor:
    """Colour at a card-coordinate point of the backdrop's rendered image."""
    point = card.mapTo(backdrop, QPoint(x, y))
    image = backdrop.grab().toImage()
    return QColor(image.pixel(point.x(), point.y()))


def test_set_thumbnail(qtbot):
    card = PageCard(0)
    qtbot.addWidget(card)

    pixmap = QPixmap(80, 100)
    pixmap.fill(QColor("red"))
    card.set_thumbnail(pixmap)

    thumbnail_label = card._thumbnail_label
    shown = thumbnail_label.pixmap()
    assert shown is not None
    assert not shown.isNull()


def test_set_selected_styles(qtbot):
    card = PageCard(0)
    qtbot.addWidget(card)

    card.set_selected(False)
    assert card.property("selected") is False
    assert not card.styleSheet()

    card.set_selected(True)
    assert card.property("selected") is True
    assert card.property("focused") is False
    assert "selected" in card.accessibleDescription().casefold()

    card.set_keyboard_focused(True)
    assert card.property("focused") is True

    sheet = app_stylesheet()
    assert "QFrame#PageCard:hover" in sheet
    assert "PageCardFocusRing" not in sheet
    assert "PageCardSelectionIndicator" not in sheet


def test_thumbnail_frame_is_stable_for_mixed_page_shapes(qtbot):
    """Loading a landscape page must not move its caption or reflow the grid."""
    card = PageCard(0)
    qtbot.addWidget(card)
    card.set_card_width(176)
    final_height = card._thumbnail_label.height()

    landscape = QPixmap(200, 100)
    landscape.fill(QColor("red"))
    card.set_thumbnail(landscape)

    shown = card._thumbnail_label.pixmap()
    assert shown is not None
    assert card._thumbnail_label.height() == final_height
    assert shown.width() <= card._thumbnail_label.width()
    assert shown.height() <= final_height


def test_theme_toggle_keeps_property_based_card_chrome(qtbot, isolated_settings):
    """O3 residual: light/dark restyle must not push inline styles onto cards."""
    app = QApplication.instance()
    assert app is not None

    card = PageCard(0)
    qtbot.addWidget(card)
    card.set_selected(True)
    assert card.property("selected") is True
    assert not card.styleSheet()

    set_light_theme(True)
    apply_app_stylesheet(app)
    assert card.property("selected") is True
    assert not card.styleSheet()
    light = app.styleSheet()
    assert 'QFrame#PageCard[selected="true"]' in light
    assert LIGHT.chrome in light

    set_light_theme(False)
    apply_app_stylesheet(app)
    assert card.property("selected") is True
    assert not card.styleSheet()
    dark = app.styleSheet()
    assert 'QFrame#PageCard[selected="true"]' in dark
    assert DARK.chrome in dark


def test_page_card_accessible_name(qtbot):
    card = PageCard(2)
    qtbot.addWidget(card)
    assert card.accessibleName() == "Page 3"
    assert "select" in card.accessibleDescription().casefold()

    card.set_logical_index(0)
    assert card.accessibleName() == "Page 1"

    card.set_page_tooltip(210, 297)
    assert card.accessibleName() == "Page 1"
    assert "210×297" in card.accessibleDescription()


@pytest.fixture
def themed(isolated_settings):
    def apply(light: bool):
        set_light_theme(light)
        return LIGHT if light else DARK

    return apply


def test_thumbnail_frame_has_no_fill_once_it_has_a_page(qtbot):
    backdrop, card = _card_on_backdrop(qtbot, _page(200, 100))
    label = card._thumbnail_label
    assert label.placeholder is False
    assert 'QLabel#PageCardThumbnail {' not in app_stylesheet()

    page = card._page_rect()
    assert (page.width(), page.height()) == (160, 80)
    # Above and below the landscape page the backdrop shows through.
    top = label.y() + 4
    bottom = label.y() + label.height() - 4
    assert _pixel(backdrop, card, 80, top) == _BACKDROP
    assert _pixel(backdrop, card, 80, bottom) == _BACKDROP
    assert _pixel(backdrop, card, 80, page.center().y()) == _PAGE


def test_page_sits_at_real_aspect_in_the_unchanged_cell(qtbot):
    _, card = _card_on_backdrop(qtbot, None)
    cell = card._thumbnail_label.size()
    for width, height in ((100, 200), (200, 100), (150, 150)):
        card.set_thumbnail(_page(width, height))
        page = card._page_rect_in_label()
        assert card._thumbnail_label.size() == cell
        assert abs(page.width() / page.height() - width / height) < 0.05
        assert card._thumbnail_label.rect().contains(page)
        assert page.center() == card._thumbnail_label.rect().center()


def test_page_shaped_placeholder_until_rendered_and_failure_text_stays(qtbot, themed):
    theme = themed(False)
    backdrop, card = _card_on_backdrop(qtbot, None)
    label = card._thumbnail_label
    assert label.placeholder is True
    assert card._page_rect_in_label() == label.rect()
    assert _pixel(backdrop, card, 80, label.y() + 40) == QColor(theme.line)

    card.set_failed()
    assert label.placeholder is True
    assert label.text() == "Page unavailable"
    assert not label.isHidden()

    card.set_thumbnail(_page(100, 140))
    assert label.placeholder is False
    assert label.text() == ""

    card.release_thumbnail()
    assert label.placeholder is True


@pytest.mark.parametrize("light", [False, True])
def test_selection_outline_is_ink_at_the_page_edge(qtbot, themed, light):
    theme = themed(light)
    backdrop, card = _card_on_backdrop(qtbot, _page(200, 100))
    page = card._page_rect()
    ink = QColor(theme.ink)
    edge = (page.center().x(), page.top())

    assert _pixel(backdrop, card, edge[0], edge[1] - 1) != ink
    card.set_selected(True)
    for offset in range(1, PAGE_OUTLINE_WIDTH + 1):
        assert _pixel(backdrop, card, edge[0], edge[1] - offset) == ink
    # Just past the outline is not ink, and the page itself is untouched.
    assert _pixel(backdrop, card, edge[0], edge[1] - PAGE_OUTLINE_WIDTH - 1) != ink
    assert _pixel(backdrop, card, edge[0], edge[1]) == _PAGE
    left = page.left() - 1
    assert _pixel(backdrop, card, left, page.center().y()) == ink

    card.set_selected(False)
    assert _pixel(backdrop, card, edge[0], edge[1] - 1) != ink


@pytest.mark.parametrize("light", [False, True])
def test_focus_ring_is_separate_from_the_selection_outline(qtbot, themed, light):
    theme = themed(light)
    backdrop, card = _card_on_backdrop(qtbot, _page(200, 100))
    page = card._page_rect()
    x, top = page.center().x(), page.top()
    ink, focus = QColor(theme.ink), QColor(theme.focus)
    ring_start = PAGE_OUTLINE_WIDTH + PAGE_RING_GAP + 1

    card.set_keyboard_focused(True)
    # Focus alone: a ring, no ink outline.
    assert _pixel(backdrop, card, x, top - 1) != ink
    assert _pixel(backdrop, card, x, top - ring_start) == focus
    assert _pixel(backdrop, card, x, top - ring_start - 1) == focus

    card.set_selected(True)
    # Both at once: ink outline, a gap that is neither, then the ring.
    assert _pixel(backdrop, card, x, top - 1) == ink
    assert _pixel(backdrop, card, x, top - PAGE_OUTLINE_WIDTH) == ink
    gap = _pixel(backdrop, card, x, top - PAGE_OUTLINE_WIDTH - PAGE_RING_GAP)
    assert gap not in (ink, focus)
    assert _pixel(backdrop, card, x, top - ring_start) == focus

    card.set_keyboard_focused(False)
    assert _pixel(backdrop, card, x, top - ring_start) != focus
    assert _pixel(backdrop, card, x, top - 1) == ink


def test_focus_ring_widens_in_high_contrast(qtbot, themed, monkeypatch):
    focus = QColor(themed(False).focus)
    monkeypatch.setattr("pagedrop.ui.page_card.prefers_high_contrast", lambda: True)
    backdrop, card = _card_on_backdrop(qtbot, _page(200, 100))
    page = card._page_rect()
    card.set_keyboard_focused(True)
    start = PAGE_OUTLINE_WIDTH + PAGE_RING_GAP + 1
    for offset in range(start, start + FOCUS_WIDTH_HIGH_CONTRAST):
        assert _pixel(backdrop, card, page.center().x(), page.top() - offset) == focus
    assert (
        _pixel(backdrop, card, page.center().x(), page.top() - start - 3) != focus
    )


@pytest.mark.parametrize("hc", [False, True])
@pytest.mark.parametrize("size", [(100, 200), (200, 100), (150, 150), (160, 226)])
@pytest.mark.parametrize("thumb", [MIN_THUMBNAIL_WIDTH, MAX_THUMBNAIL_WIDTH])
def test_selection_and_focus_chrome_fits_inside_the_card(
    qtbot, monkeypatch, hc, size, thumb
):
    monkeypatch.setattr("pagedrop.ui.page_card.prefers_high_contrast", lambda: hc)
    _, card = _card_on_backdrop(qtbot, _page(*size), thumb_width=thumb)
    card.set_selected(True)
    card.set_keyboard_focused(True)
    page = card._page_rect()
    ring = FOCUS_WIDTH_HIGH_CONTRAST if hc else 2
    reach = PAGE_OUTLINE_WIDTH + PAGE_RING_GAP + ring
    outer = page.adjusted(-reach, -reach, reach, reach)
    assert card.rect().contains(outer)


def test_chip_shows_page_order_in_the_index_colour(qtbot, themed):
    theme = themed(False)
    backdrop, card = _card_on_backdrop(qtbot, _page(200, 100))
    card.set_index_colour_provider(lambda: "index_teal")
    chip = card._order_chip
    assert chip.isHidden()

    card.set_selected(True)
    assert chip.isHidden()  # selected, but no place in the selection yet
    card.set_selection_rank(2)
    assert not chip.isHidden()
    assert chip._rank == 2

    image = chip.grab().toImage()
    assert QColor(image.pixel(4, chip.height() // 2)) == QColor(theme.index_teal)
    on_index = QColor(theme.on_index)
    glyphs = [
        QColor(image.pixel(x, y))
        for x in range(image.width())
        for y in range(image.height())
    ]
    assert any(
        abs(c.red() - on_index.red()) < 40
        and abs(c.green() - on_index.green()) < 40
        and abs(c.blue() - on_index.blue()) < 40
        for c in glyphs
    )

    # The chip sits at the page's bottom-left, inside it.
    page = card._page_rect()
    at = chip.mapTo(card, QPoint(0, 0))
    assert at.x() > page.left()
    assert page.contains(at) and page.contains(at + QPoint(chip.width(), chip.height()))
    assert at.y() + chip.height() > page.center().y()


def test_chip_follows_theme_and_document_colour_without_a_rebuild(qtbot, themed):
    _, card = _card_on_backdrop(qtbot, _page(100, 140))
    chosen = {"name": "index_clay"}
    card.set_index_colour_provider(lambda: chosen["name"])
    card.set_selected(True)
    card.set_selection_rank(1)
    chip = card._order_chip

    theme = themed(True)
    assert chip.fill_colour() == index_qcolor("index_clay")
    assert chip.fill_colour() == QColor(theme.index_clay)
    theme = themed(False)
    assert chip.fill_colour() == QColor(theme.index_clay)
    chosen["name"] = "index_plum"
    assert chip.fill_colour() == QColor(DARK.index_plum)
    # No provider, or a name that is not a token, falls back to slate.
    card.set_index_colour_provider(None)
    assert chip.fill_colour() == QColor(DARK.index_slate)
    card.set_index_colour_provider(lambda: "not_a_colour")
    assert chip.fill_colour() == QColor(DARK.index_slate)


def test_chip_hides_and_forgets_its_number_when_deselected(qtbot):
    _, card = _card_on_backdrop(qtbot, _page(100, 140))
    card.set_selected(True)
    card.set_selection_rank(3)
    assert not card._order_chip.isHidden()

    card.set_selected(False)
    assert card._order_chip.isHidden()
    assert card.selection_rank is None
    # Selecting again without a fresh rank does not resurrect the old number.
    card.set_selected(True)
    assert card._order_chip.isHidden()


def test_chip_grows_for_long_numbers(qtbot):
    _, card = _card_on_backdrop(qtbot, _page(100, 140))
    card.set_selected(True)
    card.set_selection_rank(1)
    short = card._order_chip.width()
    card.set_selection_rank(1234)
    assert card._order_chip.width() > short


def test_no_check_glyph_is_used_for_selection(qtbot):
    _, card = _card_on_backdrop(qtbot, _page(100, 140))
    card.set_selected(True)
    card.set_selection_rank(1)
    texts = [label.text() for label in card.findChildren(QLabel)]
    assert not any("✓" in text for text in texts)


def test_accessible_description_names_the_position(qtbot):
    card = PageCard(1)
    qtbot.addWidget(card)
    card.set_page_tooltip(210, 297)
    card.set_selected(True)
    card.set_selection_rank(2)
    assert card.accessibleName() == "Page 2"
    assert card.accessibleDescription().startswith("Selected, number 2 · ")
    assert "210×297" in card.accessibleDescription()

    card.set_selection_rank(3)
    assert "number 3" in card.accessibleDescription()

    card.set_selected(False)
    assert "Selected" not in card.accessibleDescription()
    assert "number" not in card.accessibleDescription()


def test_overlays_anchor_to_the_page_not_the_cell(qtbot):
    _, card = _card_on_backdrop(qtbot, _page(200, 100))
    card.set_page_overlay_visible(True)
    card.set_rotation_indicator(90)
    page = card._page_rect_in_label()
    label = card._thumbnail_label
    assert page.height() < label.height()

    page_number = card._page_overlay
    rotation = card._rotation_overlay
    assert page.contains(page_number.geometry())
    assert page.contains(rotation.geometry())
    assert rotation.y() >= page.top()
    assert page_number.geometry().bottom() <= page.bottom()


def test_the_order_chip_leaves_the_drag_payload_unchanged(qtbot, five_page_pdf, monkeypatch):
    from PyQt6.QtGui import QDrag

    from pagedrop.core.drag_mime import INTERNAL_PAGE_MIME, PAGE_TRANSFER_MIME, decode_page_indices
    from pagedrop.core.pdf_editor import PdfEditModel
    from pagedrop.core.pdf_loader import PdfLoader
    from pagedrop.core.selection_manager import SelectionManager
    from pagedrop.utils.temp_manager import TempManager

    loader = PdfLoader(str(five_page_pdf))
    model = PdfEditModel(loader.path, loader.page_count)
    selection = SelectionManager()
    selection.set_page_count(model.logical_count())
    card = PageCard(1)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    card.set_drag_context(model, selection, TempManager())

    def drag_formats_and_indices(rank: int | None):
        selection.select_single(1)
        card.set_selection_rank(rank)
        seen: dict[str, object] = {}

        def fake_exec(drag, *args, **kwargs):
            mime = drag.mimeData()
            seen["formats"] = set(mime.formats())
            seen["indices"] = decode_page_indices(mime.data(INTERNAL_PAGE_MIME))
            return Qt.DropAction.IgnoreAction

        monkeypatch.setattr(QDrag, "exec", fake_exec)
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(card, pos=QPoint(200, 200))
        qtbot.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
        return seen

    plain = drag_formats_and_indices(None)
    with_chip = drag_formats_and_indices(3)
    loader.close()

    assert plain == with_chip
    assert plain["formats"] == {INTERNAL_PAGE_MIME, PAGE_TRANSFER_MIME, "text/uri-list"}
    assert plain["indices"] == [1]
