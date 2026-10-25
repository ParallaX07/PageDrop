"""shared job runner: stage / promote / cancel / path guards / credentials."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import fitz
import pytest

from pagedrop.core.jobs import (
    BackendUnavailableError,
    CancelToken,
    JobCancelledError,
    JobContext,
    JobError,
    JobSpec,
    OutputExistsError,
    SerializedJobRunner,
    SourceOverwriteError,
    preflight_pdf_inputs,
)
from pagedrop.core.capabilities import AbsenceReason
from pagedrop.core.jobs.staging import JobStaging
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_service import FITZ_LOCK, render_ref_png
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256


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
    source_hash = file_sha256(src)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("copy", _copy_handler)
        result = runner.run(
            JobSpec.create("copy", inputs=[src], output=out),
        )
        assert result == out
        assert out.is_file()
        assert file_sha256(src) == source_hash
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

    calls = 0

    def exdev_replace(src: object, dst: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_replace(src, dst)

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


def test_cross_device_promotion_failure_preserves_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed copy never truncates the already-confirmed replacement target."""
    import errno
    import os

    from pagedrop.core.jobs.staging import JobStaging

    real_replace = os.replace
    temp = TempManager()
    try:
        staging = JobStaging(temp)
        staged = staging.stage_file("out.pdf")
        staged.write_bytes(b"new bytes")
        destination = tmp_path / "out.pdf"
        destination.write_bytes(b"existing bytes")

        def exdev_replace(src: object, dst: object) -> None:
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(os, "replace", exdev_replace)
        monkeypatch.setattr("shutil.copyfile", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy failed")))
        with pytest.raises(OSError, match="copy failed"):
            staging.promote(staged, destination)

        assert destination.read_bytes() == b"existing bytes"
        assert staged.exists()
    finally:
        monkeypatch.setattr(os, "replace", real_replace)
        temp.cleanup()


def test_cancel_removes_partial_and_orphans(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)
    source_hash = file_sha256(src)

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
        assert file_sha256(src) == source_hash
        leftovers = list(temp.get_dir().rglob("*"))
        assert not any(
            p.is_file() and p.name != ".pagedrop_owner" for p in leftovers
        )
    finally:
        temp.cleanup()


def test_never_writes_source_path(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    _write_pdf(src)
    source_hash = file_sha256(src)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("copy", _copy_handler)
        with pytest.raises(SourceOverwriteError):
            runner.run(JobSpec.create("copy", inputs=[src], output=src))
        assert file_sha256(src) == source_hash

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
    isolated_settings,
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
    assert preflight_pdf_inputs(
        [enc],
        prompt=lambda *_args: pytest.fail("Valid cached password prompted again"),
        credentials=creds,
    ) is creds
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


def test_external_wait_handler_does_not_block_fitz_lock(tmp_path: Path) -> None:
    """Office/LO-style handlers (holds_fitz=False) must not hold FITZ_LOCK.

    A parallel pdf_service render under the lock must complete while the job
    is still in its fake external wait.
    """
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    render_src = tmp_path / "render.pdf"
    _write_pdf(src)
    _write_pdf(render_src)

    entered = threading.Event()
    release = threading.Event()

    def fake_office_wait(ctx: JobContext) -> Path:
        entered.set()
        assert release.wait(timeout=5), "test never released external wait"
        ctx.staged_output.write_bytes(src.read_bytes())
        return ctx.staged_output

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("fake_office", fake_office_wait, holds_fitz=False)

        err: list[BaseException] = []

        def run_job() -> None:
            try:
                runner.run(
                    JobSpec.create("fake_office", inputs=[src], output=out),
                )
            except BaseException as exc:  # pragma: no cover
                err.append(exc)

        t = threading.Thread(target=run_job, daemon=True)
        t.start()
        assert entered.wait(timeout=5), "external-wait handler never started"

        # From a different thread than the job: lock must be free during wait.
        assert FITZ_LOCK.acquire(timeout=1.0), "FITZ_LOCK held during external wait"
        FITZ_LOCK.release()

        # Must not block for the full fake wait duration.
        t0 = time.monotonic()
        png = render_ref_png(PageRef(str(render_src), 0), width_px=64)
        elapsed = time.monotonic() - t0
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert elapsed < 1.0, f"render blocked {elapsed:.2f}s behind external wait"

        release.set()
        t.join(timeout=5)
        assert not err
        assert out.is_file()
    finally:
        release.set()
        temp.cleanup()


def test_fitz_job_serializes_parallel_render(tmp_path: Path) -> None:
    """holds_fitz=True jobs still stall parallel renders (O10 in-process ceiling).

    Documents the intentional global-lock jank: no crash, but interactive fitz
    waits until the job releases. Upgrade path remains a PDF service process.
    """
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    render_src = tmp_path / "render.pdf"
    _write_pdf(src)
    _write_pdf(render_src)

    holding = threading.Event()
    release = threading.Event()

    def long_fitz(ctx: JobContext) -> Path:
        with fitz.open(str(ctx.spec.inputs[0])) as doc:
            _ = doc[0].get_pixmap().tobytes("png")
        holding.set()
        assert release.wait(timeout=5)
        ctx.staged_output.write_bytes(src.read_bytes())
        return ctx.staged_output

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("long_fitz", long_fitz, holds_fitz=True)
        err: list[BaseException] = []

        def run_job() -> None:
            try:
                runner.run(JobSpec.create("long_fitz", inputs=[src], output=out))
            except BaseException as exc:  # pragma: no cover
                err.append(exc)

        jt = threading.Thread(target=run_job, daemon=True)
        jt.start()
        assert holding.wait(timeout=5), "fitz job never entered hold"

        assert not FITZ_LOCK.acquire(timeout=0.15), (
            "FITZ_LOCK free during holds_fitz job"
        )

        render_ms: list[float] = []
        render_err: list[BaseException] = []
        done = threading.Event()

        def run_render() -> None:
            t0 = time.monotonic()
            try:
                png = render_ref_png(PageRef(str(render_src), 0), width_px=64)
                assert png[:8] == b"\x89PNG\r\n\x1a\n"
            except BaseException as exc:  # pragma: no cover
                render_err.append(exc)
            render_ms.append((time.monotonic() - t0) * 1000)
            done.set()

        rt = threading.Thread(target=run_render, daemon=True)
        rt.start()
        time.sleep(0.25)
        assert not done.is_set(), "render finished while fitz job still held lock"
        release.set()
        assert done.wait(timeout=5)
        jt.join(timeout=5)
        rt.join(timeout=1)

        assert not err and not render_err
        assert render_ms and render_ms[0] >= 200
        assert out.is_file()
    finally:
        release.set()
        temp.cleanup()


def test_external_wait_cancel_cleans_staged_output(tmp_path: Path) -> None:
    """Cancel mid external-wait job still removes partial staged output."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)
    source_hash = file_sha256(src)

    started = threading.Event()
    allow_finish = threading.Event()
    staged_seen: list[Path] = []

    def fake_office_wait(ctx: JobContext) -> Path:
        ctx.staged_output.write_bytes(b"%PDF-partial-office")
        staged_seen.append(ctx.staging.job_dir)
        started.set()
        assert allow_finish.wait(timeout=5)
        ctx.cancel.check()
        return ctx.staged_output

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("fake_office", fake_office_wait, holds_fitz=False)
        token = CancelToken()
        err: list[BaseException] = []

        def run_job() -> None:
            try:
                runner.run(
                    JobSpec.create("fake_office", inputs=[src], output=out),
                    cancel=token,
                )
            except JobCancelledError:
                return
            except BaseException as exc:  # pragma: no cover
                err.append(exc)

        t = threading.Thread(target=run_job, daemon=True)
        t.start()
        assert started.wait(timeout=5)
        token.cancel()
        allow_finish.set()
        t.join(timeout=5)

        assert not out.exists()
        assert file_sha256(src) == source_hash
        assert staged_seen
        assert not staged_seen[0].exists()
        leftovers = list(temp.get_dir().rglob("*"))
        assert not any(
            p.is_file() and p.name != ".pagedrop_owner" for p in leftovers
        )
        assert not err
    finally:
        allow_finish.set()
        temp.cleanup()


def _two_output_handler(extra_destination: Path):
    def handler(ctx: JobContext) -> Path:
        shutil.copy2(ctx.spec.inputs[0], ctx.staged_output)
        staged_extra = ctx.staging.stage_file("extra.pdf")
        shutil.copy2(ctx.spec.inputs[0], staged_extra)
        ctx.extra_outputs.append((staged_extra, extra_destination))
        return ctx.staged_output

    return handler


def test_runner_promotes_primary_and_extra_outputs(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out" / "a.pdf"
    extra = tmp_path / "out" / "b.pdf"
    _write_pdf(src)
    source_hash = file_sha256(src)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("two", _two_output_handler(extra))
        assert runner.run(JobSpec.create("two", inputs=[src], output=out)) == out
        assert out.is_file()
        assert extra.is_file()
        assert file_sha256(src) == source_hash
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()


def test_extra_output_equal_to_input_is_rejected_before_any_promote(
    tmp_path: Path,
) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)
    source_hash = file_sha256(src)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("two", _two_output_handler(src))
        with pytest.raises(SourceOverwriteError):
            runner.run(JobSpec.create("two", inputs=[src], output=out))
        assert not out.exists()
        assert file_sha256(src) == source_hash
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()


def test_existing_extra_output_blocks_all_promotion_without_overwrite(
    tmp_path: Path,
) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    extra = tmp_path / "extra_dest.pdf"
    _write_pdf(src)
    extra.write_bytes(b"keep me")

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("two", _two_output_handler(extra))
        with pytest.raises(OutputExistsError):
            runner.run(JobSpec.create("two", inputs=[src], output=out))
        assert not out.exists()
        assert extra.read_bytes() == b"keep me"
        assert not any(temp.get_dir().glob("job_*"))

        runner.run(JobSpec.create("two", inputs=[src], output=out, overwrite=True))
        assert out.is_file()
        assert extra.read_bytes() != b"keep me"
    finally:
        temp.cleanup()


def test_two_outputs_with_one_destination_are_rejected(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("two", _two_output_handler(out))
        with pytest.raises(JobError, match="share one destination"):
            runner.run(JobSpec.create("two", inputs=[src], output=out))
        assert not out.exists()
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()


def test_primary_appearing_mid_job_is_not_clobbered(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)

    def racing_handler(ctx: JobContext) -> Path:
        shutil.copy2(ctx.spec.inputs[0], ctx.staged_output)
        out.write_bytes(b"someone else")
        return ctx.staged_output

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("race", racing_handler)
        with pytest.raises(OutputExistsError):
            runner.run(JobSpec.create("race", inputs=[src], output=out))
        assert out.read_bytes() == b"someone else"
    finally:
        temp.cleanup()


def _split_case(tmp_path: Path):
    from pagedrop.core.organize_jobs import register_organize_handlers

    src = tmp_path / "src" / "in.pdf"
    src.parent.mkdir()
    _write_pdf(src, pages=3)
    out_dir = tmp_path / "out"
    spec = JobSpec.create(
        "split",
        inputs=[src],
        output=out_dir / "in_range_0001-0001.pdf",
        options={
            "ranges": [(0, 0), (1, 1), (2, 2)],
            "output_dir": str(out_dir),
            "base_name": "in",
        },
    )
    return register_organize_handlers, spec, [src], 3


def _bates_case(tmp_path: Path):
    from pagedrop.core.modify_jobs import register_modify_handlers

    sources = []
    for name in ("a", "b"):
        src = tmp_path / "src" / f"{name}.pdf"
        src.parent.mkdir(exist_ok=True)
        _write_pdf(src)
        sources.append(src)
    out_dir = tmp_path / "out"
    spec = JobSpec.create(
        "bates",
        inputs=sources,
        output=out_dir / "a_bates.pdf",
        options={"output_dir": str(out_dir), "prefix": "X-"},
    )
    return register_modify_handlers, spec, sources, 2


def _import_case(tmp_path: Path):
    from pagedrop.core.native_conversion_jobs import register_native_conversion_handlers

    sources = []
    for name in ("a", "b"):
        src = tmp_path / "src" / f"{name}.txt"
        src.parent.mkdir(exist_ok=True)
        src.write_text(f"hello {name}", encoding="utf-8")
        sources.append(src)
    out_dir = tmp_path / "out"
    spec = JobSpec.create(
        "import_to_pdf",
        inputs=sources,
        output=out_dir / "a.pdf",
        options={"output_dir": str(out_dir)},
    )
    return register_native_conversion_handlers, spec, sources, 2


@pytest.mark.parametrize("case", [_split_case, _bates_case, _import_case])
@pytest.mark.parametrize("cancel_after_handler", [False, True])
def test_multi_output_handlers_promote_only_after_final_cancel_check(
    tmp_path: Path, case, cancel_after_handler: bool
) -> None:
    register, spec, sources, expected_count = case(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hashes = [file_sha256(p) for p in sources]
    token = CancelToken()

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register(runner)
        real = runner._handlers[spec.job_type]

        def cancelling(ctx: JobContext, _real=real.handler) -> Path:
            result = _real(ctx)
            if cancel_after_handler:
                ctx.cancel.cancel()
            return result

        runner.register(spec.job_type, cancelling, holds_fitz=real.holds_fitz)
        if cancel_after_handler:
            with pytest.raises(JobCancelledError):
                runner.run(spec, cancel=token)
            assert list(out_dir.iterdir()) == []
        else:
            runner.run(spec, cancel=token)
            assert len(list(out_dir.glob("*.pdf"))) == expected_count
        assert not any(temp.get_dir().glob("job_*"))
        assert [file_sha256(p) for p in sources] == hashes
    finally:
        temp.cleanup()


def test_failed_promotion_removes_new_outputs_and_names_replaced_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "in.pdf"
    first = tmp_path / "out" / "a.pdf"
    replaced = tmp_path / "out" / "b.pdf"
    third = tmp_path / "out" / "c.pdf"
    _write_pdf(src)
    replaced.parent.mkdir()
    replaced.write_bytes(b"old")
    source_hash = file_sha256(src)

    def handler(ctx: JobContext) -> Path:
        shutil.copy2(ctx.spec.inputs[0], ctx.staged_output)
        for name, dest in (("b.pdf", replaced), ("c.pdf", third)):
            staged = ctx.staging.stage_file(name)
            shutil.copy2(ctx.spec.inputs[0], staged)
            ctx.extra_outputs.append((staged, dest))
        return ctx.staged_output

    real_promote = JobStaging.promote
    calls: list[Path] = []

    def flaky_promote(self, staged: Path, destination: Path) -> Path:
        calls.append(destination)
        if len(calls) == 3:
            raise OSError("disk full")
        return real_promote(self, staged, destination)

    monkeypatch.setattr(JobStaging, "promote", flaky_promote)
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("three", handler)
        with pytest.raises(JobError) as info:
            runner.run(
                JobSpec.create(
                    "three", inputs=[src], output=first, overwrite=True
                )
            )
        assert str(replaced) in str(info.value)
        assert str(first) not in str(info.value)
        assert not first.exists()
        assert not third.exists()
        assert replaced.is_file()
        assert replaced.read_bytes() != b"old"
        assert file_sha256(src) == source_hash
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()


def test_extra_output_sharing_the_primary_destination_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "in.pdf"
    _write_pdf(src)
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("two", _two_output_handler(tmp_path / "out.pdf"))
        with pytest.raises(JobError, match="share one destination"):
            runner.run(
                JobSpec.create("two", inputs=[src], output=tmp_path / "out.pdf")
            )
        assert not (tmp_path / "out.pdf").exists()
    finally:
        temp.cleanup()
