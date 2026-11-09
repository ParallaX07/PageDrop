"""The start screen a tab shows until it has a document."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget

from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    encode_page_indices,
    encode_page_refs,
)
from pagedrop.core.pdf_loader import PdfLoadError
from pagedrop.ui.list_row_delegate import VALUE_ROLE
from pagedrop.ui.main_window import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.settings import (
    recent_file_entries,
    recent_files,
    remember_recent_file,
)
from pagedrop.ui.start_screen import MISSING_TEXT, NO_RECENT_TEXT, StartScreen
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256, wait_for_grid_loaded, wait_for_pdf_loaded
from tests.fixtures.generate_fixtures import generate_n_page


def _blank_tab(qtbot) -> PdfTab:
    tab = PdfTab(TempManager())
    qtbot.addWidget(tab)
    tab.resize(900, 650)
    tab.show()
    return tab


def _recent_pdfs(directory: Path, *names: str) -> list[Path]:
    """Create small PDFs and remember them, oldest first."""
    paths = []
    for name in names:
        path = directory / name
        generate_n_page(path, 1)
        remember_recent_file(path)
        paths.append(path)
    return paths


def _rows(screen: StartScreen) -> list[str]:
    return [screen.recent_list.item(i).text() for i in range(screen.recent_list.count())]


def _row(screen: StartScreen, name: str):
    for i in range(screen.recent_list.count()):
        item = screen.recent_list.item(i)
        if item.text() == name:
            return item
    raise AssertionError(f"{name} is not listed")


def _url_mime(*paths: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


def _enter(mime: QMimeData) -> QDragEnterEvent:
    return QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _move(mime: QMimeData) -> QDragMoveEvent:
    return QDragMoveEvent(
        QPoint(12, 12),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _drop(mime: QMimeData) -> QDropEvent:
    return QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


# --- which page the tab shows ----------------------------------------------


def test_blank_tab_shows_the_start_screen_not_the_grid(qtbot):
    tab = _blank_tab(qtbot)
    assert tab.is_blank
    assert tab.content_stack.currentWidget() is tab.start_screen
    assert tab.start_screen.isVisibleTo(tab)
    assert not tab.thumbnail_grid.isVisibleTo(tab)


def test_loading_a_document_swaps_to_the_grid_and_closing_returns(qtbot, five_page_pdf):
    before = file_sha256(five_page_pdf)
    tab = _blank_tab(qtbot)

    tab.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid
    assert not tab.start_screen.isVisibleTo(tab)

    tab.close_loader()
    assert tab.is_blank
    assert tab.content_stack.currentWidget() is tab.start_screen
    assert file_sha256(five_page_pdf) == before


def test_viewer_mode_is_unaffected_by_the_start_screen(qtbot, five_page_pdf):
    tab = _blank_tab(qtbot)
    tab.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)

    tab.show_preview_at(0)
    assert tab.is_viewer_mode()
    assert tab.content_stack.currentWidget() is tab.preview_widget
    tab.close_preview()
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid
    assert not tab.is_viewer_mode()


def test_a_failed_open_leaves_the_start_screen_showing(qtbot, corrupt_pdf):
    before = file_sha256(corrupt_pdf)
    tab = _blank_tab(qtbot)
    with pytest.raises(PdfLoadError):
        tab.load_pdf(str(corrupt_pdf))
    assert tab.is_blank
    assert tab.content_stack.currentWidget() is tab.start_screen
    assert file_sha256(corrupt_pdf) == before


def test_a_failed_open_in_a_document_tab_keeps_the_grid(qtbot, five_page_pdf, corrupt_pdf):
    tab = _blank_tab(qtbot)
    tab.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    with pytest.raises(PdfLoadError):
        tab.load_pdf(str(corrupt_pdf))
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid


def test_cancelled_password_leaves_the_start_screen_showing(
    main_window, qtbot, tmp_path, monkeypatch
):
    import fitz

    locked = tmp_path / "locked.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(
        str(locked),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw="secret",
        owner_pw="secret",
    )
    doc.close()
    before = file_sha256(locked)
    monkeypatch.setattr(main_window, "_prompt_pdf_password", lambda *a, **k: None)

    tab = main_window._active_tab()
    main_window._load_pdf(str(locked), tab=tab)

    assert tab.is_blank
    assert tab.content_stack.currentWidget() is tab.start_screen
    assert file_sha256(locked) == before


def test_page_transfer_into_a_blank_tab_swaps_to_the_grid(qtbot, five_page_pdf):
    source = _blank_tab(qtbot)
    source.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, source.thumbnail_grid)
    refs = [source.edit_model.page_at(0), source.edit_model.page_at(1)]
    target = _blank_tab(qtbot)

    target.init_from_page_refs(refs)
    assert target.content_stack.currentWidget() is target.thumbnail_grid


def test_recovery_draft_restores_into_the_grid(qtbot, five_page_pdf, tmp_path):
    source = PdfTab(TempManager(), recovery_dir=tmp_path / "drafts")
    (tmp_path / "drafts").mkdir()
    qtbot.addWidget(source)
    source.resize(900, 650)
    source.show()
    source.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, source.thumbnail_grid)
    source.thumbnail_grid.selection_manager.select_single(1)
    assert source.thumbnail_grid.delete_selected_pages()
    source._sync_dirty_from_model()
    draft = source.recovery_path
    assert draft is not None and draft.exists()

    restored = _blank_tab(qtbot)
    restored.restore_recovery_draft(draft)
    assert restored.content_stack.currentWidget() is restored.thumbnail_grid
    assert restored.edit_model.logical_count() == 4


def test_deleting_every_page_keeps_the_grid_for_undo(qtbot, five_page_pdf):
    tab = _blank_tab(qtbot)
    tab.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    tab.thumbnail_grid.selection_manager.select_all()
    assert tab.thumbnail_grid.delete_selected_pages()
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid
    assert not tab.start_screen.isVisibleTo(tab)


# --- buttons ---------------------------------------------------------------


def test_buttons_trigger_their_actions_and_mirror_them(qtbot):
    screen = StartScreen()
    qtbot.addWidget(screen)
    open_a, merge_a, tools_a = QAction("&Open PDF", screen), QAction("&Merge PDFs", screen), QAction("All &tools", screen)
    hits: list[str] = []
    open_a.triggered.connect(lambda: hits.append("open"))
    merge_a.triggered.connect(lambda: hits.append("merge"))
    tools_a.triggered.connect(lambda: hits.append("tools"))
    screen.bind_actions(open_a, merge_a, tools_a)

    assert [b.text() for b in (screen.open_button, screen.merge_button, screen.tools_button)] == [
        "Open PDF",
        "Merge PDFs",
        "All tools",
    ]
    assert [b.accessibleName() for b in (screen.open_button, screen.merge_button, screen.tools_button)] == [
        "Open PDF",
        "Merge PDFs",
        "All tools",
    ]
    screen.open_button.click()
    screen.merge_button.click()
    screen.tools_button.click()
    assert hits == ["open", "merge", "tools"]

    merge_a.setEnabled(False)
    assert not screen.merge_button.isEnabled()
    screen.merge_button.click()
    assert hits == ["open", "merge", "tools"]
    merge_a.setEnabled(True)
    merge_a.setText("Merge files")
    assert screen.merge_button.isEnabled()
    assert screen.merge_button.text() == "Merge files"
    assert screen.merge_button.accessibleName() == "Merge files"


def test_rebinding_actions_drops_the_previous_ones(qtbot):
    screen = StartScreen()
    qtbot.addWidget(screen)

    def trio(tag: str):
        actions = [QAction(f"{tag} {n}", screen) for n in ("open", "merge", "tools")]
        return actions

    first, second = trio("first"), trio("second")
    hits: list[str] = []
    for action in (*first, *second):
        action.triggered.connect(lambda _=False, a=action: hits.append(a.text()))
    screen.bind_actions(*first)
    screen.bind_actions(*second)
    screen.bind_actions(*second)  # same actions twice must not double-fire

    screen.open_button.click()
    assert hits == ["second open"]
    first[0].setText("Changed")  # no longer projected onto the button
    assert screen.open_button.text() == "second open"


def test_main_window_buttons_follow_the_registered_actions(main_window, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    screen = main_window._active_tab().start_screen
    for button, key in (
        (screen.open_button, "open"),
        (screen.merge_button, "merge"),
        (screen.tools_button, "tools"),
    ):
        action = main_window._actions[key]
        assert button.text() == action.text().replace("&", "")
        assert button.isEnabled() == action.isEnabled()

    main_window._actions["merge"].setEnabled(False)
    assert not screen.merge_button.isEnabled()
    main_window._actions["merge"].setEnabled(True)

    triggered: list[bool] = []
    main_window._actions["open"].triggered.connect(lambda: triggered.append(True))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([], ""))
    screen.open_button.click()
    assert triggered == [True]


def test_tab_order_runs_buttons_then_recent_files(qtbot, isolated_settings):
    _recent_pdfs(isolated_settings, "a.pdf")
    screen = StartScreen()
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)

    order, widget = [], screen.open_button
    while widget not in order:
        order.append(widget)
        widget = widget.nextInFocusChain()
        while not (widget.focusPolicy() & Qt.FocusPolicy.TabFocus) or not widget.isVisibleTo(screen):
            widget = widget.nextInFocusChain()
    chain = [w for w in order if w in (
        screen.open_button, screen.merge_button, screen.tools_button, screen.recent_list
    )]
    assert chain == [
        screen.open_button, screen.merge_button, screen.tools_button, screen.recent_list
    ]
    assert screen.recent_list.accessibleName() == "Recent files"


# --- recent files ----------------------------------------------------------


def test_recent_files_are_listed_newest_first_with_folder_and_full_path(
    qtbot, isolated_settings
):
    a, b = _recent_pdfs(isolated_settings, "a.pdf", "b.pdf")
    screen = StartScreen()
    qtbot.addWidget(screen)

    assert _rows(screen) == ["b.pdf", "a.pdf"]
    row = _row(screen, "a.pdf")
    assert row.data(VALUE_ROLE) == str(a.resolve().parent)
    assert row.toolTip() == str(a.resolve())
    assert not screen._no_recent.isVisibleTo(screen)


def test_a_missing_recent_file_is_marked_in_text_and_for_assistive_tech(
    qtbot, isolated_settings
):
    a, b = _recent_pdfs(isolated_settings, "a.pdf", "b.pdf")
    a.unlink()
    screen = StartScreen()
    qtbot.addWidget(screen)

    missing = _row(screen, "a.pdf")
    assert missing.data(VALUE_ROLE) == MISSING_TEXT
    assert missing.data(Qt.ItemDataRole.AccessibleTextRole) == "a.pdf, missing"
    present = _row(screen, "b.pdf")
    assert present.data(VALUE_ROLE) != MISSING_TEXT
    assert not present.data(Qt.ItemDataRole.AccessibleTextRole).endswith(", missing")
    # The menu keeps omitting files that are gone.
    assert [Path(p).name for p in recent_files()] == ["b.pdf"]


def test_a_missing_entry_survives_remembering_another_file(qtbot, isolated_settings):
    a, b = _recent_pdfs(isolated_settings, "a.pdf", "b.pdf")
    a.unlink()
    (c,) = _recent_pdfs(isolated_settings, "c.pdf")

    assert [(Path(p).name, ok) for p, ok in recent_file_entries()] == [
        ("c.pdf", True),
        ("b.pdf", True),
        ("a.pdf", False),
    ]
    screen = StartScreen()
    qtbot.addWidget(screen)
    assert _rows(screen) == ["c.pdf", "b.pdf", "a.pdf"]
    assert c.exists()


def test_recent_entries_are_deduped_and_capped(isolated_settings):
    from pagedrop.ui.settings import RECENT_FILES_MAX

    paths = _recent_pdfs(isolated_settings, *[f"f{n:02d}.pdf" for n in range(RECENT_FILES_MAX + 3)])
    remember_recent_file(paths[-1])
    remember_recent_file(paths[-2])

    entries = recent_file_entries()
    assert len(entries) == RECENT_FILES_MAX
    assert [Path(p).name for p, _ in entries][:2] == [paths[-2].name, paths[-1].name]
    assert len({p for p, _ in entries}) == RECENT_FILES_MAX


def _store_unreadable_recent(directory: Path, monkeypatch, error: Exception) -> Path:
    """Store a recent path whose filesystem checks raise *error*."""
    from pagedrop.ui import settings as settings_module

    bad = directory / "locked" / "hidden.pdf"
    settings_module._settings().setValue(settings_module.KEY_RECENT_FILES, [str(bad)])
    real_exists, real_resolve, real_is_file = Path.exists, Path.resolve, Path.is_file

    def guard(real):
        def wrapper(self, *args, **kwargs):
            if self.name == "hidden.pdf":
                raise error
            return real(self, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(Path, "exists", guard(real_exists))
    monkeypatch.setattr(Path, "resolve", guard(real_resolve))
    monkeypatch.setattr(Path, "is_file", guard(real_is_file))
    return bad


@pytest.mark.parametrize("error", [PermissionError("denied"), RuntimeError("symlink loop")])
def test_an_unreadable_recent_path_is_listed_as_missing(
    qtbot, isolated_settings, monkeypatch, error
):
    bad = _store_unreadable_recent(isolated_settings, monkeypatch, error)
    (a,) = _recent_pdfs(isolated_settings, "a.pdf")

    assert recent_file_entries() == [(str(a.resolve()), True), (str(bad), False)]
    assert [Path(p).name for p in recent_files()] == ["a.pdf"]

    screen = StartScreen()
    qtbot.addWidget(screen)
    screen.show()
    assert _rows(screen) == ["a.pdf", "hidden.pdf"]
    assert _row(screen, "hidden.pdf").data(VALUE_ROLE) == MISSING_TEXT

    (b,) = _recent_pdfs(isolated_settings, "b.pdf")
    assert [Path(p).name for p, _ in recent_file_entries()] == ["b.pdf", "a.pdf", "hidden.pdf"]
    assert b.exists()


@pytest.mark.parametrize("error", [PermissionError("denied"), RuntimeError("symlink loop")])
def test_activating_an_unreadable_recent_row_warns_without_raising(
    main_window, qtbot, isolated_settings, monkeypatch, error
):
    bad = _store_unreadable_recent(isolated_settings, monkeypatch, error)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text, *a, **k: warnings.append(text)
    )
    tab = main_window._active_tab()
    tab.start_screen.refresh_recent()
    item = tab.start_screen.recent_list.item(0)
    assert item.data(VALUE_ROLE) == MISSING_TEXT

    tab.start_screen.recent_list.itemClicked.emit(item)

    assert warnings == [f"File not found:\n{bad}"]
    assert tab.is_blank


def test_a_full_list_drops_missing_entries_before_live_ones(isolated_settings):
    from pagedrop.ui.settings import RECENT_FILES_MAX

    paths = _recent_pdfs(
        isolated_settings, *[f"f{n:02d}.pdf" for n in range(RECENT_FILES_MAX)]
    )
    # The oldest entries are the missing ones; a live file sits among the newest.
    missing = paths[:6]
    for path in missing:
        path.unlink()
    live = paths[6:]
    (new,) = _recent_pdfs(isolated_settings, "new.pdf")

    entries = recent_file_entries()
    assert len(entries) == RECENT_FILES_MAX
    assert Path(entries[0][0]).name == "new.pdf"
    kept = {Path(p).name for p, ok in entries if ok}
    assert kept == {p.name for p in live} | {new.name}
    assert [Path(p).name for p, ok in entries if not ok] == [
        p.name for p in reversed(missing)
    ][:5]


def test_no_recent_files_shows_one_quiet_line(qtbot, isolated_settings):
    screen = StartScreen()
    qtbot.addWidget(screen)
    assert screen.recent_list.count() == 0
    assert screen.recent_list.isHidden()
    assert screen._recent_title.isHidden()
    assert not screen._no_recent.isHidden()
    assert screen._no_recent.text() == NO_RECENT_TEXT == "No recent files"


def test_the_list_is_refreshed_every_time_the_screen_is_shown(qtbot, isolated_settings):
    a, b = _recent_pdfs(isolated_settings, "a.pdf", "b.pdf")
    screen = StartScreen()
    qtbot.addWidget(screen)
    screen.show()
    assert _row(screen, "a.pdf").data(VALUE_ROLE) != MISSING_TEXT

    screen.hide()
    a.unlink()
    screen.show()
    assert _row(screen, "a.pdf").data(VALUE_ROLE) == MISSING_TEXT
    assert _row(screen, "b.pdf").data(VALUE_ROLE) != MISSING_TEXT


def test_clicking_a_present_row_opens_it_unchanged(
    main_window, qtbot, isolated_settings
):
    (a,) = _recent_pdfs(isolated_settings, "a.pdf")
    before = file_sha256(a)
    main_window.resize(900, 650)
    main_window.show()
    qtbot.waitExposed(main_window)
    tab = main_window._active_tab()
    screen = tab.start_screen
    screen.refresh_recent()
    rect = screen.recent_list.visualItemRect(screen.recent_list.item(0))

    qtbot.mouseClick(
        screen.recent_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )
    wait_for_pdf_loaded(qtbot, main_window)

    assert not tab.is_blank
    assert Path(tab.pdf_path).resolve() == a.resolve()
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid
    assert file_sha256(a) == before


def test_enter_on_a_row_requests_it(qtbot, isolated_settings):
    (a,) = _recent_pdfs(isolated_settings, "a.pdf")
    screen = StartScreen()
    qtbot.addWidget(screen)
    screen.show()
    screen.recent_list.setFocus()
    screen.recent_list.setCurrentRow(0)

    with qtbot.waitSignal(screen.recent_file_requested) as blocker:
        qtbot.keyClick(screen.recent_list, Qt.Key.Key_Return)
    assert Path(blocker.args[0]).resolve() == a.resolve()


def test_activating_a_missing_row_warns_and_stays_blank(
    main_window, qtbot, isolated_settings, monkeypatch
):
    (a,) = _recent_pdfs(isolated_settings, "a.pdf")
    a.unlink()
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text, *a, **k: warnings.append(text)
    )
    tab = main_window._active_tab()
    tab.start_screen.refresh_recent()
    item = tab.start_screen.recent_list.item(0)
    assert item.data(VALUE_ROLE) == MISSING_TEXT

    tab.start_screen.recent_list.itemClicked.emit(item)

    assert len(warnings) == 1
    assert warnings[0].startswith("File not found:") and str(a.resolve()) in warnings[0]
    assert tab.is_blank
    assert tab.content_stack.currentWidget() is tab.start_screen


def test_the_open_recent_menu_still_warns_for_a_missing_file(
    main_window, qtbot, isolated_settings, monkeypatch
):
    (a,) = _recent_pdfs(isolated_settings, "a.pdf")
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text, *a, **k: warnings.append(text)
    )
    main_window._populate_open_recent_menu()
    action = next(
        act for act in main_window._open_recent_menu.actions() if act.data()
    )
    a.unlink()
    action.trigger()
    assert warnings and warnings[0].startswith("File not found:")


# --- drops -----------------------------------------------------------------


def test_drop_active_follows_an_accepted_pdf_drag(qtbot, five_page_pdf):
    tab = _blank_tab(qtbot)
    screen = tab.start_screen
    mime = _url_mime(five_page_pdf)
    assert not screen.property("dropActive")

    enter = _enter(mime)
    screen.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert screen.property("dropActive") is True

    move = _move(mime)
    screen.dragMoveEvent(move)
    assert move.isAccepted()
    assert screen.property("dropActive") is True

    screen.dragLeaveEvent(QDragLeaveEvent())
    assert screen.property("dropActive") is False


def test_drop_clears_drop_active_and_opens_the_pdf(qtbot, five_page_pdf):
    before = file_sha256(five_page_pdf)
    tab = _blank_tab(qtbot)
    screen = tab.start_screen
    mime = _url_mime(five_page_pdf)
    screen.dragEnterEvent(_enter(mime))
    assert screen.property("dropActive") is True

    drop = _drop(mime)
    with qtbot.waitSignal(tab.thumbnail_grid.open_pdfs_requested) as blocker:
        screen.dropEvent(drop)
    assert drop.isAccepted()
    assert screen.property("dropActive") is False
    assert [Path(p).resolve() for p in blocker.args[0]] == [five_page_pdf.resolve()]
    assert file_sha256(five_page_pdf) == before


def test_a_non_pdf_drag_is_rejected_and_not_highlighted(qtbot, tmp_path):
    note = tmp_path / "notes.txt"
    note.write_text("not a pdf")
    tab = _blank_tab(qtbot)
    screen = tab.start_screen
    mime = _url_mime(note)

    enter = _enter(mime)
    screen.dragEnterEvent(enter)
    assert not enter.isAccepted()
    assert not screen.property("dropActive")

    drop = _drop(mime)
    screen.dropEvent(drop)
    assert not drop.isAccepted()
    assert tab.is_blank


def test_dropping_a_pdf_opens_it_in_the_blank_tab(main_window, qtbot, five_page_pdf):
    before = file_sha256(five_page_pdf)
    tab = main_window._active_tab()
    mime = _url_mime(five_page_pdf)
    tab.start_screen.dragEnterEvent(_enter(mime))
    assert main_window.statusBar().currentMessage() == "Release to place pages"

    drop = _drop(mime)
    tab.start_screen.dropEvent(drop)
    assert drop.isAccepted()
    wait_for_pdf_loaded(qtbot, main_window)

    assert not tab.is_blank
    assert tab.edit_model.logical_count() == 5
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid
    assert main_window.statusBar().currentMessage() != "Release to place pages"
    assert file_sha256(five_page_pdf) == before


def test_a_page_transfer_drop_onto_the_start_screen_still_lands(
    main_window, qtbot, five_page_pdf, monkeypatch
):
    before = file_sha256(five_page_pdf)
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    source = main_window._active_tab()
    blank = main_window._tab_manager.add_blank_tab()
    main_window._tab_manager.setCurrentWidget(blank)

    refs = [source.edit_model.page_at(i) for i in (0, 2)]
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, encode_page_refs(refs))
    mime.setData(INTERNAL_PAGE_MIME, encode_page_indices([0, 2]))

    enter = _enter(mime)
    blank.start_screen.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert blank.start_screen.property("dropActive") is True

    drop = _drop(mime)
    blank.start_screen.dropEvent(drop)

    assert drop.isAccepted()
    assert blank.start_screen.property("dropActive") is False
    assert not blank.is_blank
    assert blank.content_stack.currentWidget() is blank.thumbnail_grid
    assert [
        (blank.edit_model.page_at(i).source_path, blank.edit_model.page_at(i).source_index)
        for i in range(blank.edit_model.logical_count())
    ] == [(str(five_page_pdf), 0), (str(five_page_pdf), 2)]
    assert source.edit_model.logical_count() == 5
    assert file_sha256(five_page_pdf) == before


def test_the_grid_handlers_work_while_the_grid_is_the_hidden_page(qtbot, five_page_pdf):
    tab = _blank_tab(qtbot)
    grid = tab.thumbnail_grid
    assert not grid.isVisibleTo(tab)
    mime = _url_mime(five_page_pdf)

    enter = _enter(mime)
    grid.dragEnterEvent(enter)
    assert enter.isAccepted()
    with qtbot.waitSignal(grid.open_pdfs_requested):
        grid.dropEvent(_drop(mime))


# --- whole-window drops ----------------------------------------------------


def test_window_drop_on_a_blank_tab_opens_it(main_window, qtbot, five_page_pdf):
    before = file_sha256(five_page_pdf)
    tab = main_window._active_tab()
    mime = _url_mime(five_page_pdf)

    enter = _enter(mime)
    main_window.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert tab.start_screen.property("dropActive") is True

    drop = _drop(mime)
    main_window.dropEvent(drop)
    assert drop.isAccepted()
    assert tab.start_screen.property("dropActive") is False
    wait_for_pdf_loaded(qtbot, main_window)

    assert not tab.is_blank
    assert main_window._tab_manager.count() == 1
    assert file_sha256(five_page_pdf) == before


def test_window_drag_leave_clears_the_highlight(main_window, five_page_pdf):
    tab = main_window._active_tab()
    mime = _url_mime(five_page_pdf)  # the events do not own it
    main_window.dragEnterEvent(_enter(mime))
    assert tab.start_screen.property("dropActive") is True
    main_window.dragLeaveEvent(QDragLeaveEvent())
    assert tab.start_screen.property("dropActive") is False


def test_window_drop_while_a_document_is_open_is_ignored(
    main_window, qtbot, five_page_pdf, one_page_pdf
):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = main_window._active_tab()
    mime = _url_mime(one_page_pdf)

    enter = _enter(mime)
    main_window.dragEnterEvent(enter)
    assert not enter.isAccepted()
    move = _move(mime)
    main_window.dragMoveEvent(move)
    assert not move.isAccepted()
    drop = _drop(mime)
    main_window.dropEvent(drop)
    assert not drop.isAccepted()

    assert main_window._tab_manager.count() == 1
    assert Path(tab.pdf_path).resolve() == five_page_pdf.resolve()
    assert tab.edit_model.logical_count() == 5
    assert not tab.start_screen.property("dropActive")


def test_window_drop_on_a_tool_page_is_ignored(main_window, five_page_pdf):
    page = QWidget()
    page.tool_page_id = "test-tool-drop"
    page.WINDOW_TITLE = "Test tool"
    main_window._tab_manager.add_page(page, "Test tool")
    assert main_window._active_tab() is None

    mime = _url_mime(five_page_pdf)  # the events do not own it
    enter = _enter(mime)
    main_window.dragEnterEvent(enter)
    assert not enter.isAccepted()
    drop = _drop(mime)
    main_window.dropEvent(drop)
    assert not drop.isAccepted()


def test_the_window_accepts_drops(main_window):
    assert main_window.acceptDrops()


# --- layout ---------------------------------------------------------------


def test_the_column_is_centred_and_bounded(qtbot, isolated_settings):
    _recent_pdfs(isolated_settings, "a.pdf")
    tab = _blank_tab(qtbot)
    tab.resize(1400, 900)
    screen = tab.start_screen
    column = screen.findChild(QWidget, "StartScreenColumn")
    viewport = screen._scroll.viewport()

    def centre():
        return column.mapTo(viewport, column.rect().center()).x()

    qtbot.waitUntil(lambda: abs(centre() - viewport.width() // 2) <= 1)
    assert column.width() <= 440
    assert column.width() < viewport.width()


def test_the_compact_floor_holds_with_recent_files(
    main_window, qtbot, isolated_settings
):
    _recent_pdfs(isolated_settings, *[f"f{n}.pdf" for n in range(6)])
    main_window.show()
    qtbot.waitExposed(main_window)
    tab = main_window._active_tab()
    tab.start_screen.refresh_recent()
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(
        lambda: main_window.size().width() == MIN_WINDOW_WIDTH
        and main_window.size().height() == MIN_WINDOW_HEIGHT
    )

    hint = main_window.centralWidget().minimumSizeHint()
    assert hint.width() <= MIN_WINDOW_WIDTH
    assert hint.height() <= MIN_WINDOW_HEIGHT - main_window.menuWidget().height()
    window_hint = main_window.minimumSizeHint()
    assert window_hint.width() <= MIN_WINDOW_WIDTH
    assert window_hint.height() <= MIN_WINDOW_HEIGHT
    # What does not fit scrolls instead of clipping.
    scroll = tab.start_screen._scroll
    qtbot.waitUntil(lambda: scroll.verticalScrollBar().maximum() > 0)
    assert not scroll.horizontalScrollBar().isVisible()


def test_logo_and_labels_have_accessible_names(qtbot):
    screen = StartScreen()
    qtbot.addWidget(screen)
    logo = screen.findChild(QLabel, "GridEmptyLogo")
    assert logo.accessibleName() == "PageDrop logo"
    screen.show()
    assert logo.pixmap() is not None and not logo.pixmap().isNull()
    assert screen.accessibleName() == "Open a PDF"
    for button in screen.findChildren(QPushButton):
        assert button.accessibleName()


@pytest.mark.parametrize("count", [1, 10])
@pytest.mark.parametrize(
    ("light", "high_contrast"),
    [(False, False), (True, False), (False, True), (True, True)],
    ids=["dark", "light", "dark-hc", "light-hc"],
)
@pytest.mark.parametrize("theme_after_show", [False, True], ids=["styled-first", "restyled-live"])
def test_every_recent_row_is_fully_visible_without_an_inner_scrollbar(
    qtbot, isolated_settings, count, light, high_contrast, theme_after_show
):
    from pagedrop.ui.theme import app_stylesheet

    _recent_pdfs(isolated_settings, *[f"sample{n}.pdf" for n in range(count)])
    screen = StartScreen()
    qtbot.addWidget(screen)
    recent = screen.recent_list
    real_sheet = app_stylesheet(light=light, high_contrast=high_contrast)
    if theme_after_show:
        # Rows without item padding first, so the real sheet has to change their height.
        screen.setStyleSheet("QListWidget#PanelList::item { padding: 0; }")
    else:
        screen.setStyleSheet(real_sheet)
    screen.resize(1400, 860)
    screen.show()
    qtbot.waitExposed(screen)

    def fully_visible() -> bool:
        if recent.count() != count or not recent.isVisible():
            return False
        last = recent.visualItemRect(recent.item(count - 1))
        return last.bottom() < recent.viewport().height() and last.height() > 0

    def check() -> None:
        qtbot.waitUntil(fully_visible, timeout=5000)
        # The row is as tall as the padded item really paints, not just its text.
        assert recent.visualItemRect(recent.item(0)).height() >= recent.fontMetrics().height()
        assert recent.viewport().height() >= recent.sizeHintForRow(0) * count
        assert not recent.verticalScrollBar().isVisible()

    check()
    if theme_after_show:
        unpadded = recent.visualItemRect(recent.item(0)).height()
        screen.setStyleSheet(real_sheet)
        qtbot.waitUntil(
            lambda: recent.visualItemRect(recent.item(0)).height() > unpadded, timeout=5000
        )
        check()
    screen.refresh_recent()
    check()
