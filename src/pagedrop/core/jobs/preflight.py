"""Protected-PDF preflight for every PDF-input job (Qt-free).

UI supplies a prompt callback (same wording as the editor password dialog).
Credentials stay in ``RuntimeCredentials`` only — never on ``JobSpec``,
settings, or exception text.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.jobs.errors import JobCancelledError
from pagedrop.core.pdf_loader import (
    PdfLoader,
    PdfPasswordError,
    PdfPasswordRequiredError,
)

PasswordPrompt = Callable[[str, bool], str | None]
"""``(filename, incorrect) -> password | None`` — ``None`` means user cancelled."""


def preflight_pdf_inputs(
    paths: Sequence[str | Path],
    *,
    prompt: PasswordPrompt,
    credentials: RuntimeCredentials | None = None,
    cancel: CancelToken | None = None,
) -> RuntimeCredentials:
    """Unlock each PDF input; one stored credential per path; retry / cancel cleanly.

    Opens and closes loaders only to verify access — does not keep fitz docs alive.
    """
    creds = credentials or RuntimeCredentials()
    for raw in paths:
        if cancel is not None:
            cancel.check()
        path = str(raw)
        # Native convert jobs may mix non-PDF inputs; only unlock real PDFs.
        if Path(path).suffix.lower() != ".pdf":
            continue
        filename = Path(path).name
        password = creds.get(path)

        while True:
            if cancel is not None:
                cancel.check()
            try:
                loader = PdfLoader(path, password=password)
            except PdfPasswordRequiredError:
                password = prompt(filename, False)
                if password is None:
                    raise JobCancelledError(
                        f"Password prompt cancelled for {filename}"
                    ) from None
                continue
            except PdfPasswordError:
                password = prompt(filename, True)
                if password is None:
                    raise JobCancelledError(
                        f"Password prompt cancelled for {filename}"
                    ) from None
                continue
            else:
                loader.close()
                if password is not None:
                    creds.set(path, password)
                break
    return creds
