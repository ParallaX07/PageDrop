"""Phase 18 UI tests — cross-window page drag (copy / Shift+move)."""

from __future__ import annotations

import fitz
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QMimeData, QPointF, Qt
from PyQt6.QtGui import QDrag, QDropEvent

from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    PageTransferPayloadError,
    decode_page_refs,
    encode_page_indices,
    encode_page_refs,
)
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import PdfLoader, PdfNotFoundError
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256, wait_for_grid_loaded


def _load_grid(qtbot, pdf_path) -> ThumbnailGrid:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    grid.show()
    loader = PdfLoader(str(pdf_path))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    grid._reflow_grid(force=True)
    return grid


def _blank_tab(qtbot) -> PdfTab:
    tab = PdfTab(TempManager())
    qtbot.addWidget(tab)
    tab.resize(900, 650)
    tab.show()
    return tab


def _model_refs(grid: ThumbnailGrid) -> list[tuple[str, int]]:
    assert grid._model is not None
    return [
        (grid._model.page_at(i).source_path, grid._model.page_at(i).source_index)
        for i in range(grid._model.logical_count())
    ]


def _transfer_mime(
    refs: list[PageRef],
    logical_indices: list[int],
):
    class _Mime:
        def hasFormat(self, fmt: str) -> bool:
            return fmt in (PAGE_TRANSFER_MIME, INTERNAL_PAGE_MIME)

        def data(self, fmt: str) -> bytes:
            if fmt == PAGE_TRANSFER_MIME:
                return encode_page_refs(refs)
            if fmt == INTERNAL_PAGE_MIME:
                return encode_page_indices(logical_indices)
            return b""

    return _Mime()


def _cross_window_drop(
    target: ThumbnailGrid,
    source: ThumbnailGrid,
    logical_indices: list[int],
    *,
    shift: bool = False,
    drop_index: int = 0,
) -> bool:
    assert source._model is not None
    refs = [source._model.page_at(i) for i in logical_indices]
    mime = _transfer_mime(refs, logical_indices)
    return target._handle_page_transfer(
        refs,
        drop_index,
        move=shift,
        source_grid=source,
        mime=mime,
    )


def test_page_transfer_mime_roundtrip():
    refs = [
        PageRef("/tmp/a.pdf", 0),
        PageRef("/tmp/b.pdf", 2),
    ]
    assert decode_page_refs(encode_page_refs(refs)) == refs


def test_cross_window_grid_drop_uses_insertion_index(qtbot, five_page_pdf):
    """Grid drops keep cursor-based insertion (append_only=False), not tab-bar append."""
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, five_page_pdf)
    assert source._model is not None

    ref = source._model.page_at(0)
    mime = _transfer_mime([ref], [0])
    assert target._handle_page_transfer(
        [ref],
        1,
        move=False,
        source_grid=source,
        mime=mime,
        append_only=False,
    )

    refs = _model_refs(target)
    assert len(refs) == 6
    assert refs[1] == (str(five_page_pdf), 0)
    assert refs[-1] != (str(five_page_pdf), 0)


def test_tab_bar_drop_emits_when_source_grid_is_none(qtbot, five_page_pdf):
    """Successful tab-bar copy still notifies when source_grid is omitted."""
    target_tab = _load_tab(qtbot, five_page_pdf)
    target = target_tab.thumbnail_grid
    assert target._model is not None

    ref = target._model.page_at(0)
    mime = _transfer_mime([ref], [0])
    emitted: list[tuple[int, str, bool]] = []
    target.pages_transferred_via_tab_bar.connect(
        lambda count, name, moved: emitted.append((count, name, moved))
    )

    assert target.handle_tab_bar_page_drop(
        [ref],
        move=False,
        source_grid=None,
        mime=mime,
    )
    assert emitted == [(1, five_page_pdf.name, False)]


def test_tab_bar_drop_appends_to_end_not_insertion_index(qtbot, five_page_pdf):
    """Tab-bar drops use append_only=True even when grids differ (cross-window)."""
    source_tab = _load_tab(qtbot, five_page_pdf)
    target_tab = _load_tab(qtbot, five_page_pdf)
    source = source_tab.thumbnail_grid
    target = target_tab.thumbnail_grid
    assert source._model is not None

    ref = source._model.page_at(0)
    mime = _transfer_mime([ref], [0])
    assert target.handle_tab_bar_page_drop(
        [ref],
        move=False,
        source_grid=source,
        mime=mime,
    )

    refs = _model_refs(target)
    assert len(refs) == 6
    assert refs[-1] == (str(five_page_pdf), 0)
    assert refs[1] != (str(five_page_pdf), 0)


def test_cross_window_grid_drop_via_drop_event(qtbot, five_page_pdf, one_page_pdf, monkeypatch):
    """Full grid dropEvent path still accepts cross-grid PAGE_TRANSFER_MIME."""
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)
    assert source._model is not None

    refs = [source._model.page_at(1), source._model.page_at(3)]
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, encode_page_refs(refs))
    mime.setData(INTERNAL_PAGE_MIME, encode_page_indices([1, 3]))
    monkeypatch.setattr(
        ThumbnailGrid,
        "_grid_for_widget",
        staticmethod(lambda _widget: source),
    )
    monkeypatch.setattr(target, "drop_index_at_pos", lambda _pos: 1)

    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    target.dropEvent(drop)

    assert drop.isAccepted()
    assert _model_refs(target) == [
        (str(one_page_pdf), 0),
        (str(five_page_pdf), 1),
        (str(five_page_pdf), 3),
    ]


def test_copy_pages_from_window_a_to_b(qtbot, five_page_pdf, one_page_pdf):
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)

    assert _cross_window_drop(target, source, [1, 3], drop_index=1)

    assert target._model is not None
    assert target._model.logical_count() == 3
    assert _model_refs(target) == [
        (str(one_page_pdf), 0),
        (str(five_page_pdf), 1),
        (str(five_page_pdf), 3),
    ]
    assert source._model is not None
    assert source._model.logical_count() == 5
    assert not source._model.is_dirty()


def test_failed_move_rolls_back_target_insert(qtbot, five_page_pdf, one_page_pdf, monkeypatch):
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)
    source_before = _model_refs(source)
    target_before = _model_refs(target)
    transfer_errors: list[str] = []
    target.page_transfer_failed.connect(transfer_errors.append)
    original_remove = ThumbnailGrid.remove_pages_by_indices

    def fail_remove_on_source(self, logical_indices: list[int]) -> bool:
        if self is source:
            return False
        return original_remove(self, logical_indices)

    monkeypatch.setattr(
        ThumbnailGrid, "remove_pages_by_indices", fail_remove_on_source
    )

    assert not _cross_window_drop(target, source, [2], shift=True, drop_index=1)

    assert _model_refs(source) == source_before
    assert _model_refs(target) == target_before
    assert transfer_errors == ["Could not move pages from the source document."]


def test_shift_drop_moves_pages_between_windows(qtbot, five_page_pdf, one_page_pdf):
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)

    assert _cross_window_drop(target, source, [2], shift=True, drop_index=1)

    assert _model_refs(target) == [
        (str(one_page_pdf), 0),
        (str(five_page_pdf), 2),
    ]
    assert source._model is not None
    assert source._model.logical_count() == 4
    assert source._model.is_dirty()


def test_same_window_drop_still_reorders(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)

    assert grid.reorder_pages_by_drop([4], 0)

    assert _model_refs(grid) == [
        (str(five_page_pdf), 4),
        (str(five_page_pdf), 0),
        (str(five_page_pdf), 1),
        (str(five_page_pdf), 2),
        (str(five_page_pdf), 3),
    ]


def _load_tab(qtbot, pdf_path) -> PdfTab:
    tab = _blank_tab(qtbot)
    tab.load_pdf(str(pdf_path))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    return tab


def test_cross_window_drop_marks_target_dirty(qtbot, five_page_pdf, one_page_pdf):
    source_tab = _load_tab(qtbot, five_page_pdf)
    target_tab = _load_tab(qtbot, one_page_pdf)
    source = source_tab.thumbnail_grid
    target = target_tab.thumbnail_grid
    assert not source_tab.is_dirty
    assert not target_tab.is_dirty

    assert _cross_window_drop(target, source, [1, 3], drop_index=1)

    assert target_tab.is_dirty
    assert not source_tab.is_dirty


def test_move_marks_source_dirty(qtbot, five_page_pdf, one_page_pdf):
    source_tab = _load_tab(qtbot, five_page_pdf)
    target_tab = _load_tab(qtbot, one_page_pdf)
    source = source_tab.thumbnail_grid
    target = target_tab.thumbnail_grid
    assert not source_tab.is_dirty
    assert not target_tab.is_dirty

    assert _cross_window_drop(target, source, [2], shift=True, drop_index=1)

    assert source_tab.is_dirty
    assert target_tab.is_dirty


def test_blank_tab_inits_on_cross_window_drop(qtbot, five_page_pdf):
    source = _load_grid(qtbot, five_page_pdf)
    tab = _blank_tab(qtbot)
    target = tab.thumbnail_grid

    assert _cross_window_drop(target, source, [0, 1])

    assert not tab.is_blank
    assert tab.edit_model is not None
    assert tab.edit_model.logical_count() == 2
    wait_for_grid_loaded(qtbot, target)
    assert _model_refs(target) == [
        (str(five_page_pdf), 0),
        (str(five_page_pdf), 1),
    ]


def test_outbound_drag_includes_transfer_payload(qtbot, five_page_pdf, monkeypatch):
    from PyQt6.QtCore import QPoint as QtPoint

    grid = _load_grid(qtbot, five_page_pdf)
    card = grid._cards[1]
    grid.selection_manager.select_single(1)

    captured_refs: list[PageRef] = []

    def capture_mime(drag: QDrag) -> None:
        mime = drag.mimeData()
        assert mime is not None
        assert mime.hasFormat(PAGE_TRANSFER_MIME)
        captured_refs.extend(decode_page_refs(mime.data(PAGE_TRANSFER_MIME)))

    def fake_exec(self, *args, **kwargs):
        capture_mime(self)
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(QDrag, "exec", fake_exec)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QtPoint(50, 50))
    qtbot.mouseMove(card, pos=QtPoint(200, 200))

    assert captured_refs == [PageRef(str(five_page_pdf), 1)]


def test_two_windows_same_pdf_allowed(qtbot, five_page_pdf, qapp):
    from pagedrop.ui.window_manager import WindowManager

    manager = WindowManager(qapp)
    window_a = manager.open_new_window()
    window_b = manager.open_new_window()
    qtbot.addWidget(window_a)
    qtbot.addWidget(window_b)

    tab_a = window_a._tab_manager.widget(0)
    tab_b = window_b._tab_manager.widget(0)
    assert isinstance(tab_a, PdfTab)
    assert isinstance(tab_b, PdfTab)

    tab_a.load_pdf(str(five_page_pdf))
    tab_b.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, tab_a.thumbnail_grid)
    wait_for_grid_loaded(qtbot, tab_b.thumbnail_grid)

    assert _cross_window_drop(
        tab_b.thumbnail_grid,
        tab_a.thumbnail_grid,
        [0],
        drop_index=1,
    )

    assert tab_b.edit_model is not None
    assert tab_b.edit_model.logical_count() == 6


def test_merge_opens_as_editor_tab(qtbot, five_page_pdf, qapp):
    from pagedrop.ui.window_manager import WindowManager

    manager = WindowManager(qapp)
    editor = manager.open_new_window()
    qtbot.addWidget(editor)
    tab = editor._tab_manager.widget(0)
    assert isinstance(tab, PdfTab)
    tab.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)

    editor._open_merge_window()
    merge = editor._merge_window
    assert merge is not None
    assert editor._tab_manager.currentWidget() is merge
    assert editor._tab_manager.indexOf(merge) >= 0

BAD_PAYLOADS = [
    pytest.param(b"not json", id="bad-json"),
    pytest.param(b"\xff\xfe", id="not-utf8"),
    pytest.param(b'{"source_path": "x", "source_index": 0}', id="object-not-list"),
    pytest.param(b"[42]", id="item-not-object"),
    pytest.param(b'[{"source_index": 0}]', id="missing-path"),
    pytest.param(b'[{"source_path": "x"}]', id="missing-index"),
    pytest.param(b'[{"source_path": "x", "source_index": "zero"}]', id="text-index"),
    pytest.param(b'[{"source_path": "x", "source_index": 1.5}]', id="float-index"),
    pytest.param(b'[{"source_path": "x", "source_index": null}]', id="null-index"),
    pytest.param(b'[{"source_path": 7, "source_index": 0}]', id="numeric-path"),
]


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_decode_page_refs_rejects_malformed_payload(payload):
    with pytest.raises(PageTransferPayloadError):
        decode_page_refs(payload)


def _raw_drop(target, payload: bytes, source, monkeypatch, *, shift=False) -> QDropEvent:
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, payload)
    monkeypatch.setattr(
        ThumbnailGrid, "_grid_for_widget", staticmethod(lambda _widget: source)
    )
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.MoveAction if shift else Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier,
    )
    target.dropEvent(drop)
    return drop


def _out_of_range_payloads(path) -> list[bytes]:
    return [
        encode_page_refs([PageRef(str(path), 5)]),
        encode_page_refs([PageRef(str(path), -1)]),
        # One bad ref rejects the whole drop, even next to valid ones.
        encode_page_refs([PageRef(str(path), 0), PageRef(str(path), 99)]),
    ]


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_malformed_grid_drop_is_rejected_visibly(
    qtbot, five_page_pdf, one_page_pdf, monkeypatch, payload
):
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)
    before = _model_refs(target)
    source_hash = file_sha256(five_page_pdf)
    errors: list[str] = []
    target.page_transfer_failed.connect(errors.append)

    drop = _raw_drop(target, payload, source, monkeypatch)

    assert not drop.isAccepted()
    assert len(errors) == 1
    assert _model_refs(target) == before
    assert file_sha256(five_page_pdf) == source_hash


@pytest.mark.parametrize("index", [0, 1, 2])
def test_out_of_range_grid_drop_is_rejected_visibly(
    qtbot, five_page_pdf, one_page_pdf, monkeypatch, index
):
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)
    before = _model_refs(target)
    source_hash = file_sha256(five_page_pdf)
    errors: list[str] = []
    target.page_transfer_failed.connect(errors.append)

    payload = _out_of_range_payloads(five_page_pdf)[index]
    drop = _raw_drop(target, payload, source, monkeypatch)

    assert not drop.isAccepted()
    assert len(errors) == 1
    assert _model_refs(target) == before
    assert file_sha256(five_page_pdf) == source_hash


def test_out_of_range_drop_into_blank_tab_leaves_it_blank(
    qtbot, five_page_pdf, monkeypatch
):
    source = _load_grid(qtbot, five_page_pdf)
    tab = _blank_tab(qtbot)
    errors: list[str] = []
    tab.thumbnail_grid.page_transfer_failed.connect(errors.append)

    payload = encode_page_refs([PageRef(str(five_page_pdf), 5)])
    drop = _raw_drop(tab.thumbnail_grid, payload, source, monkeypatch)

    assert not drop.isAccepted()
    assert len(errors) == 1
    assert tab.is_blank
    assert tab.edit_model is None
    assert tab._loader_cache == {}


def test_shift_drop_from_another_process_reports_copy_not_move(
    qtbot, five_page_pdf, one_page_pdf, monkeypatch
):
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)
    assert source._model is not None
    payload = encode_page_refs([source._model.page_at(1), source._model.page_at(2)])
    copied: list[int] = []
    inserted: list[tuple[int, str]] = []
    target.pages_copied_not_moved.connect(copied.append)
    target.cross_window_pages_inserted.connect(
        lambda count, name: inserted.append((count, name))
    )

    drop = _raw_drop(target, payload, None, monkeypatch, shift=True)

    assert drop.isAccepted()
    assert copied == [2]
    assert inserted == []
    assert len(_model_refs(target)) == 3
    assert source._model.logical_count() == 5


def test_plain_drop_from_another_process_keeps_insert_wording(
    qtbot, five_page_pdf, one_page_pdf, monkeypatch
):
    source = _load_grid(qtbot, five_page_pdf)
    target = _load_grid(qtbot, one_page_pdf)
    assert source._model is not None
    payload = encode_page_refs([source._model.page_at(1)])
    copied: list[int] = []
    inserted: list[tuple[int, str]] = []
    target.pages_copied_not_moved.connect(copied.append)
    target.cross_window_pages_inserted.connect(
        lambda count, name: inserted.append((count, name))
    )

    drop = _raw_drop(target, payload, None, monkeypatch)

    assert drop.isAccepted()
    assert copied == []
    assert inserted == [(1, five_page_pdf.name)]


def _unlocked_encrypted_tab(qtbot, tmp_path) -> tuple[PdfTab, str]:
    path = tmp_path / "locked.pdf"
    doc = fitz.open()
    try:
        for n in range(3):
            doc.new_page(width=200, height=200).insert_text((40, 80), f"secret {n}")
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="pw",
            owner_pw="pw",
        )
    finally:
        doc.close()
    tab = _blank_tab(qtbot)
    tab.load_pdf(str(path), password="pw")
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    return tab, str(path)


def test_encrypted_pages_drop_on_loaded_tab(qtbot, tmp_path, one_page_pdf):
    source_tab, path = _unlocked_encrypted_tab(qtbot, tmp_path)
    target_tab = _load_tab(qtbot, one_page_pdf)
    source_hash = file_sha256(path)
    errors: list[str] = []
    target_tab.thumbnail_grid.page_transfer_failed.connect(errors.append)

    assert _cross_window_drop(
        target_tab.thumbnail_grid, source_tab.thumbnail_grid, [0, 2], drop_index=1
    )

    assert errors == []
    assert _model_refs(target_tab.thumbnail_grid) == [
        (str(one_page_pdf), 0),
        (path, 0),
        (path, 2),
    ]
    wait_for_grid_loaded(qtbot, target_tab.thumbnail_grid)
    assert file_sha256(path) == source_hash


def test_encrypted_pages_drop_on_blank_tab(qtbot, tmp_path):
    source_tab, path = _unlocked_encrypted_tab(qtbot, tmp_path)
    target_tab = _blank_tab(qtbot)
    source_hash = file_sha256(path)
    errors: list[str] = []
    target_tab.thumbnail_grid.page_transfer_failed.connect(errors.append)

    assert _cross_window_drop(
        target_tab.thumbnail_grid, source_tab.thumbnail_grid, [1]
    )

    assert errors == []
    assert not target_tab.is_blank
    assert _model_refs(target_tab.thumbnail_grid) == [(path, 1)]
    wait_for_grid_loaded(qtbot, target_tab.thumbnail_grid)
    assert file_sha256(path) == source_hash


def test_rejected_encrypted_drop_on_blank_tab_keeps_nothing_open(qtbot, tmp_path):
    source_tab, path = _unlocked_encrypted_tab(qtbot, tmp_path)
    target_tab = _blank_tab(qtbot)
    errors: list[str] = []
    target_tab.thumbnail_grid.page_transfer_failed.connect(errors.append)
    refs = [PageRef(path, 9)]

    assert not target_tab.thumbnail_grid._handle_page_transfer(
        refs,
        0,
        move=False,
        source_grid=source_tab.thumbnail_grid,
        mime=_transfer_mime(refs, [9]),
    )

    assert len(errors) == 1
    assert target_tab.is_blank
    assert target_tab._loader_cache == {}
    assert target_tab.credentials.get(path) is None


def _free_deleted_widgets() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _two_windows_with_pending_move(qtbot, qapp, pdf_path):
    """Window A holds the source; a Shift+drop moved page 0 into a blank tab of B."""
    from pagedrop.ui.window_manager import WindowManager

    manager = WindowManager(qapp)
    window_a = manager.open_new_window()
    window_b = manager.open_new_window()
    qtbot.addWidget(window_a)
    tab_a = window_a._tab_manager.widget(0)
    tab_a.load_pdf(str(pdf_path))
    wait_for_grid_loaded(qtbot, tab_a.thumbnail_grid)
    blank_b = window_b._tab_manager.add_blank_tab()

    assert _cross_window_drop(
        blank_b.thumbnail_grid, tab_a.thumbnail_grid, [0], shift=True
    )
    assert window_a._pending_move_undo is not None
    assert tab_a.edit_model.logical_count() == 4
    return window_a, window_b, tab_a, blank_b


def test_move_undo_after_target_window_closed(qtbot, qapp, five_page_pdf):
    window_a, window_b, tab_a, blank_b = _two_windows_with_pending_move(
        qtbot, qapp, five_page_pdf
    )
    target_grid = blank_b.thumbnail_grid
    window_b.close()
    _free_deleted_widgets()
    assert sip.isdeleted(target_grid)

    window_a._on_transient_move_undo()

    assert window_a.statusBar().currentMessage() == "Move undo is no longer available"
    assert tab_a.edit_model.logical_count() == 4


def test_move_undo_after_target_tab_closed(qtbot, qapp, five_page_pdf):
    window_a, window_b, tab_a, blank_b = _two_windows_with_pending_move(
        qtbot, qapp, five_page_pdf
    )
    qtbot.addWidget(window_b)
    target_grid = blank_b.thumbnail_grid
    window_b._tab_manager.removeTab(window_b._tab_manager.indexOf(blank_b))
    sip.delete(blank_b)
    assert sip.isdeleted(target_grid)

    window_a._on_transient_move_undo()

    assert window_a.statusBar().currentMessage() == "Move undo is no longer available"
    assert tab_a.edit_model.logical_count() == 4


def test_move_undo_still_works_while_target_is_open(qtbot, qapp, five_page_pdf):
    window_a, window_b, tab_a, blank_b = _two_windows_with_pending_move(
        qtbot, qapp, five_page_pdf
    )
    qtbot.addWidget(window_b)

    window_a._on_transient_move_undo()

    assert tab_a.edit_model.logical_count() == 5
    assert blank_b.is_blank


def test_rejected_second_source_closes_blank_tab_loaders(
    qtbot, tmp_path, five_page_pdf, monkeypatch
):
    source = _load_grid(qtbot, five_page_pdf)
    tab = _blank_tab(qtbot)
    missing = tmp_path / "gone.pdf"
    refs = [PageRef(str(five_page_pdf), 0), PageRef(str(missing), 0)]

    with pytest.raises(PdfNotFoundError):
        tab.thumbnail_grid._handle_page_transfer(
            refs,
            0,
            move=False,
            source_grid=source,
            mime=_transfer_mime(refs, [0, 1]),
        )

    assert tab.is_blank
    assert tab._loader_cache == {}
