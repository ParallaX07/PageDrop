"""User-visible update states and recovery actions, without network or installers."""

from datetime import UTC, datetime, timedelta

import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QWidget

from pagedrop.ui.update_checker import UpdateCoordinator, UpdateState
from pagedrop.ui.update_presenter import UpdatePresenter
from pagedrop.ui.update_messages import update_error_message
from pagedrop.utils.update_checker import (
    RateLimitedError, ReleaseInfo, ReleaseDataError, ReleaseNotFoundError,
    UpdateCancelledError, UpdateNetworkError, UpdateTimeoutError,
    UpdateStorageError, UpdateVerificationError,
)
from pagedrop.utils.update_windows import UpdateLaunchCancelledError, WindowsUpdateError


@pytest.fixture
def presenter(qapp, qtbot, isolated_settings):
    class Manager(QObject):
        def __init__(self):
            super().__init__()
            self.primary = QWidget()
            self.windows = [self.primary]
            self.update_coordinator = UpdateCoordinator(qapp, supported=True, check=lambda *_: None)
    manager = Manager()
    qtbot.addWidget(manager.primary)
    result = UpdatePresenter(manager)
    yield result
    manager.update_coordinator.stop()
    qapp.removeEventFilter(result)
    if result.dialog:
        result.dialog.close()
    result.deleteLater()


def labels(presenter):
    return [button.text() for button in presenter.dialog.buttons.buttons()]


def test_blocked_check_shows_deadline_and_does_not_latch_manual(presenter):
    c = presenter._coordinator
    c._check_finished(None, RateLimitedError(datetime.now(UTC) + timedelta(minutes=5)))
    presenter.check_manually(presenter._manager.primary)
    assert "Try again after" in presenter.dialog.message.text()
    assert labels(presenter) == ["Open releases page", "Close"]
    assert not presenter._manual
    message = presenter.dialog.message.text()
    presenter._on_check_succeeded(None)
    assert presenter.dialog.message.text() == message


def test_manual_check_and_success(qtbot, presenter):
    with qtbot.waitSignal(presenter._coordinator.check_succeeded):
        presenter.check_manually(presenter._manager.primary)
    assert presenter.dialog.message.text() == "PageDrop is up to date."
    assert "Close" in labels(presenter)


@pytest.mark.parametrize("state,expected", [
    (UpdateState.CHECKING, "Checking for updates"),
    (UpdateState.DOWNLOADING, "Downloading update"),
    (UpdateState.READY, "ready to install"),
    (UpdateState.PREPARING, "preparing installation"),
    (UpdateState.HANDING_OFF, "preparing installation"),
])
def test_active_state_feedback(presenter, state, expected):
    presenter._coordinator._set_state(state)
    presenter.check_manually(presenter._manager.primary)
    assert expected in presenter.dialog.message.text()


def test_available_offer_is_reopened_without_network(presenter):
    c = presenter._coordinator
    c._release = ReleaseInfo("1.2.3", "v1.2.3", "PageDrop-1.2.3-Setup.exe",
                             "https://github.com/ParallaX07/PageDrop/releases/download/v1.2.3/PageDrop-1.2.3-Setup.exe",
                             1, "<b>plain notes</b>", "a" * 64)
    c._set_state(UpdateState.AVAILABLE)
    presenter.check_manually(presenter._manager.primary)
    assert "Download update" in labels(presenter)
    assert c._worker is None
    assert presenter.dialog.notes.toPlainText() == "<b>plain notes</b>"


def test_offer_actions_are_centered_and_fit(presenter, qtbot):
    c = presenter._coordinator
    c._release = ReleaseInfo("1.2.3", "v1.2.3", "name", "url", 1, "", "a" * 64)
    c._set_state(UpdateState.AVAILABLE)
    presenter.check_manually(presenter._manager.primary)
    dialog = presenter.dialog
    dialog.show()
    qtbot.waitUntil(lambda: dialog.buttons.width() > 0)
    actions = dialog.buttons.buttons()
    left = actions[0].geometry().left()
    right = dialog.buttons.width() - actions[-1].geometry().right() - 1
    assert abs(left - right) <= 1
    assert dialog.minimumWidth() >= dialog.minimumSizeHint().width()


@pytest.mark.parametrize("error,expected", [
    (UpdateNetworkError("private"), "internet connection"),
    (UpdateTimeoutError("private"), "timed out"),
    (ReleaseNotFoundError("private"), "No published update information"),
    (ReleaseDataError("private"), "could not be verified"),
    (UpdateStorageError("private"), "disk space"),
    (UpdateVerificationError("private"), "unverified file was deleted"),
    (UpdateLaunchCancelledError("private"), "verified update is ready"),
    (WindowsUpdateError("private"), "documents remain open"),
    (RuntimeError("private"), "unexpected problem"),
])
def test_sanitized_error_messages(error, expected):
    message = update_error_message(error)
    assert expected in message
    assert "private" not in message


def test_manual_error_and_download_recovery_buttons(presenter):
    presenter._manual = True
    presenter._coordinator._check_finished(None, RuntimeError("secret"))
    assert "secret" not in presenter.dialog.message.text()
    assert "Open releases page" in labels(presenter)
    presenter._coordinator._release = ReleaseInfo("1.2.3", "v1.2.3", "name", "url", 1, "", "a" * 64)
    presenter._on_download_failed(update_error_message(UpdateCancelledError()))
    assert "canceled" in presenter.dialog.message.text()
    assert {"Try again", "Open releases page", "Close"} <= set(labels(presenter))


def test_cancellation_returns_to_offer(presenter):
    c = presenter._coordinator
    c._release = ReleaseInfo("1.2.3", "v1.2.3", "name", "url", 1, "", "a" * 64)
    c._set_state(UpdateState.DOWNLOADING)
    c._download_finished(None, UpdateCancelledError())
    assert c.state is UpdateState.AVAILABLE
    assert "canceled" in presenter.dialog.message.text()
    assert "Download update" in labels(presenter)


def test_release_fallback_uses_fixed_url_and_reports_browser_failure(presenter, monkeypatch):
    import pagedrop.ui.update_presenter as module
    opened = []
    monkeypatch.setattr(module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or False)
    presenter._manual = True
    presenter._on_check_failed("Unable to check")
    next(b for b in presenter.dialog.buttons.buttons() if b.text() == "Open releases page").click()
    assert opened == ["https://github.com/ParallaX07/PageDrop/releases"]
    assert "could not open your browser" in presenter.dialog.message.text()


def test_storage_failure_is_visible_and_leaves_offer(presenter, monkeypatch):
    import pagedrop.ui.update_checker as module
    c = presenter._coordinator
    c._release = ReleaseInfo("1.2.3", "v1.2.3", "name", "url", 1, "", "a" * 64)
    c._set_state(UpdateState.AVAILABLE)
    monkeypatch.setattr(module, "UpdateStorage", lambda: (_ for _ in ()).throw(PermissionError("secret")))
    presenter.check_manually(presenter._manager.primary)
    next(b for b in presenter.dialog.buttons.buttons() if b.text() == "Download update").click()
    assert c.state is UpdateState.AVAILABLE
    assert "disk space" in presenter.dialog.message.text()
    assert "Try again" in labels(presenter)
    presenter.show_installation_error(update_error_message(UpdateLaunchCancelledError()))
    assert {"Try again", "Open releases page", "Close"} <= set(labels(presenter))
