"""shared job runner: stage / promote / cancel / path guards / credentials."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import fitz
import pytest

from pagedrop.core.jobs import (
    BackendUnavailableError,
    CancelToken,
    JobCancelledError,
    JobContext,
    JobSpec,
    OutputExistsError,
    RuntimeCredentials,
    SerializedJobRunner,
    SourceOverwriteError,
    preflight_pdf_inputs,
)
from pagedrop.core.capabilities import AbsenceReason
from pagedrop.utils.temp_manager import TempManager


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    try:
        for _ in range(pages):
            doc.new_page(width=200, height=200)
        doc.save(str(path))
    finally:
        doc.close()


def _encrypted_pdf(path: Path, *, password: str = "secret") -> None:
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw="owner",
        )
    finally:
        doc.close()


def _copy_handler(ctx: JobContext) -> Path:
    src = Path(ctx.spec.inputs[0])
    ctx.cancel.check()
    ctx.progress(0.5, "Copying…")
    shutil.copy2(src, ctx.staged_output)
    ctx.cancel.check()
    return ctx.staged_output


def test_job_success_promotes_staged_output(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)
    source_hash = _file_hash(src)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("copy", _copy_handler)
        result = runner.run(
            JobSpec.create("copy", inputs=[src], output=out),
        )
        assert result == out
        assert out.is_file()
        assert _file_hash(src) == source_hash
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()


def test_promote_falls_back_on_cross_device_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.replace fails with EXDEV when /tmp and home are different mounts."""
    import errno
    import os

    from pagedrop.core.jobs.staging import JobStaging

    real_replace = os.replace

    def exdev_replace(src: object, dst: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "replace", exdev_replace)

    temp = TempManager()
    try:
        staging = JobStaging(temp)
        staged = staging.stage_file("out.pdf")
        staged.write_bytes(b"%PDF-1.4 cross-device")
        dest = tmp_path / "Downloads" / "out.pdf"
        result = staging.promote(staged, dest)
        assert result == dest
        assert dest.read_bytes() == b"%PDF-1.4 cross-device"
        assert not staged.exists()
    finally:
        monkeypatch.setattr(os, "replace", real_replace)
        temp.cleanup()


def test_cancel_removes_partial_and_orphans(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)
    source_hash = _file_hash(src)

    def cancelling_handler(ctx: JobContext) -> Path:
        ctx.staged_output.write_bytes(b"%PDF-partial")
        ctx.cancel.cancel()
        ctx.cancel.check()
        return ctx.staged_output

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("cancel_me", cancelling_handler)
        with pytest.raises(JobCancelledError):
            runner.run(JobSpec.create("cancel_me", inputs=[src], output=out))
        assert not out.exists()
        assert _file_hash(src) == source_hash
        leftovers = list(temp.get_dir().rglob("*"))
        assert not any(p.is_file() for p in leftovers)
    finally:
        temp.cleanup()


def test_never_writes_source_path(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    _write_pdf(src)
    source_hash = _file_hash(src)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("copy", _copy_handler)
        with pytest.raises(SourceOverwriteError):
            runner.run(JobSpec.create("copy", inputs=[src], output=src))
        assert _file_hash(src) == source_hash

        existing = tmp_path / "exists.pdf"
        _write_pdf(existing)
        with pytest.raises(OutputExistsError):
            runner.run(
                JobSpec.create("copy", inputs=[src], output=existing, overwrite=False)
            )
    finally:
        temp.cleanup()


def test_protected_pdf_uses_runtime_credential_without_persisting_it(
    tmp_path: Path,
) -> None:
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    out = tmp_path / "unlocked-copy.pdf"

    prompts: list[tuple[str, bool]] = []
    replies = iter(["wrong", "secret"])

    def prompt(filename: str, incorrect: bool) -> str | None:
        prompts.append((filename, incorrect))
        return next(replies)

    creds = preflight_pdf_inputs([enc], prompt=prompt)
    assert len(prompts) == 2
    assert prompts[0] == ("locked.pdf", False)
    assert prompts[1] == ("locked.pdf", True)
    assert creds.get(enc) == "secret"
    assert "secret" not in repr(creds)
    assert "secret" not in str(creds)

    with pytest.raises(TypeError, match="must not be pickled"):
        creds.__getstate__()

    spec = JobSpec.create("copy", inputs=[enc], output=out)
    persisted = spec.to_persistable_dict()
    assert "password" not in persisted
    assert "secret" not in str(persisted)
    assert "secret" not in str(spec.options)

    # Settings must not gain a password key from job machinery.
    from pagedrop.ui import settings as ui_settings

    before_keys = set(ui_settings._settings().allKeys())

    def open_with_password(ctx: JobContext) -> Path:
        from pagedrop.core.pdf_loader import PdfLoader

        pw = ctx.credentials.get(ctx.spec.inputs[0])
        loader = PdfLoader(ctx.spec.inputs[0], password=pw)
        try:
            loader.doc.save(str(ctx.staged_output))
        finally:
            loader.close()
        return ctx.staged_output

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("copy", open_with_password)
        result = runner.run(spec, credentials=creds)
        assert result.is_file()
        # Output should open without a password (saved decrypted copy).
        check = fitz.open(str(result))
        try:
            assert not check.needs_pass
            assert len(check) == 1
        finally:
            check.close()
    finally:
        temp.cleanup()

    after_keys = set(ui_settings._settings().allKeys())
    assert after_keys == before_keys


def test_preflight_cancel_aborts_cleanly(tmp_path: Path) -> None:
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc)

    def prompt_cancel(_filename: str, _incorrect: bool) -> str | None:
        return None

    with pytest.raises(JobCancelledError):
        preflight_pdf_inputs([enc], prompt=prompt_cancel)


def test_backend_unavailable_error_is_typed() -> None:
    err = BackendUnavailableError(
        "ghostscript",
        AbsenceReason.ENGINE_MISSING,
        detail="gs not on PATH",
    )
    assert err.capability_id == "ghostscript"
    assert err.reason is AbsenceReason.ENGINE_MISSING
    assert "ghostscript" in str(err)
    assert "gs not on PATH" in str(err)


def test_cancel_token_check() -> None:
    token = CancelToken()
    token.check()
    token.cancel()
    with pytest.raises(JobCancelledError):
        token.check()


def test_run_filters_non_path_options(tmp_path: Path) -> None:
    """Nested option values must not reach ensure_no_fitz_document."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    sidecar = tmp_path / "note.txt"
    _write_pdf(src)

    seen_options: list[dict] = []

    def handler(ctx: JobContext) -> Path:
        seen_options.append(dict(ctx.spec.options))
        shutil.copy2(ctx.spec.inputs[0], ctx.staged_output)
        return ctx.staged_output

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("copy", handler)
        result = runner.run(
            JobSpec.create(
                "copy",
                inputs=[src],
                output=out,
                options={
                    "updates": {"title": "Nested"},
                    "labels": [{"startpage": 0}],
                    "ranges": [(0, 1)],
                    "flag": True,
                    "count": 3,
                    "output_dir": str(tmp_path),
                    "note_path": sidecar,
                },
            ),
        )
        assert result == out
        assert seen_options[0]["updates"] == {"title": "Nested"}
        assert seen_options[0]["output_dir"] == str(tmp_path)
        assert seen_options[0]["note_path"] == sidecar
    finally:
        temp.cleanup()
