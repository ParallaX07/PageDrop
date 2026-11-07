"""Opening files named on the command line."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import file_sha256, wait_for_pdf_loaded


def test_two_paths_open_in_the_blank_tab_and_a_new_tab(
    main_window, one_page_pdf, five_page_pdf, qtbot
):
    manager = main_window._tab_manager
    blank = manager.active_tab
    assert manager.count() == 1 and blank.is_blank
    before = (file_sha256(one_page_pdf), file_sha256(five_page_pdf))

    main_window.open_command_line_paths([str(one_page_pdf), str(five_page_pdf)])
    wait_for_pdf_loaded(qtbot, main_window)

    assert manager.count() == 2
    assert not blank.is_blank
    assert manager.widget(0) is blank
    assert Path(blank.edit_model.original_path) == Path(one_page_pdf)
    assert Path(manager.widget(1).edit_model.original_path) == Path(five_page_pdf)
    assert (file_sha256(one_page_pdf), file_sha256(five_page_pdf)) == before


def test_missing_and_non_pdf_paths_are_reported(main_window, one_page_pdf, tmp_path, qtbot):
    text = tmp_path / "notes.txt"
    text.write_text("not a pdf")
    missing = tmp_path / "gone.pdf"

    main_window.show()
    qtbot.waitExposed(main_window)
    main_window.open_command_line_paths([str(missing), str(text), str(one_page_pdf)])
    wait_for_pdf_loaded(qtbot, main_window)

    toast = main_window._toast
    assert toast.isVisible()
    assert toast._message.property("kind") == "error"
    message = toast._message.text()
    assert "gone.pdf: file not found" in message
    assert "notes.txt: not a PDF file" in message
    # The valid file still opened, in the blank tab.
    assert main_window._tab_manager.count() == 1
    assert not main_window._tab_manager.active_tab.is_blank


def test_only_bad_paths_leave_the_blank_tab_and_show_an_error(main_window, tmp_path, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    main_window.open_command_line_paths([str(tmp_path / "gone.pdf")])
    assert main_window._tab_manager.active_tab.is_blank
    assert main_window._toast.isVisible()
    assert "gone.pdf" in main_window._toast._message.text()
