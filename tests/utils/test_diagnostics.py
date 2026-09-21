from __future__ import annotations

from pagedrop.utils.diagnostics import configure_terminal_logging, log_failure


def test_log_failure_includes_context_and_traceback(capsys):
    configure_terminal_logging()
    try:
        raise ValueError("disk full")
    except ValueError as exc:
        log_failure("Save PDF", exc, output="/tmp/output.pdf")

    stderr = capsys.readouterr().err
    assert "Save PDF failed (ValueError: disk full) output=/tmp/output.pdf" in stderr
    assert "ValueError: disk full" in stderr
