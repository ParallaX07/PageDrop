"""Phase 27 core — compress, repair, encrypt/decrypt, sanitize."""

from __future__ import annotations

from pathlib import Path

import subprocess
import sys

import fitz
import pytest

from pagedrop.core import optimize_secure as ops
from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.jobs.errors import JobCancelledError, JobError, SourceOverwriteError
from pagedrop.core.jobs import CancelToken, JobSpec, SerializedJobRunner
from pagedrop.core.optimize_secure_jobs import register_optimize_secure_handlers
from pagedrop.core.pdf_tools import metadata_get, normalize_pdf_page_size
from pagedrop.core.thread_policy import FITZ_LOCK
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256


def _make_pdf(
    path: Path,
    *,
    text: str = "hello",
    title: str = "Secret Title",
    author: str = "Author",
) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), text, fontsize=18)
        doc.set_metadata({"title": title, "author": author, "creator": "PageDropTest"})
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_save_profiles_documented() -> None:
    assert set(ops.SAVE_PROFILES) == {"fast", "lossless", "max"}
    lossless = ops.resolve_save_profile("lossless")
    assert lossless.garbage == 3
    assert lossless.clean is True
    assert lossless.deflate is True
    assert ops.resolve_save_profile(lossless) is lossless
    with pytest.raises(ValueError, match="Unknown save profile"):
        ops.resolve_save_profile("linearize")  # type: ignore[arg-type]


def test_lossy_presets_documented_dpi_and_quality() -> None:
    assert set(ops.LOSSY_PROFILES) == {"screen", "ebook", "print"}
    screen = ops.resolve_lossy_profile("screen")
    assert screen.dpi == 72
    assert screen.jpeg_quality == 50
    assert screen.dpi_threshold == 100
    assert screen.dpi_threshold > screen.dpi
    ebook = ops.resolve_lossy_profile("ebook")
    assert ebook.dpi == 150 and ebook.jpeg_quality == 70
    print_p = ops.resolve_lossy_profile("print")
    assert print_p.dpi == 300 and print_p.jpeg_quality == 85
    assert ops.resolve_lossy_profile(screen) is screen
    with pytest.raises(ValueError, match="Unknown lossy profile"):
        ops.resolve_lossy_profile("ultra")  # type: ignore[arg-type]


def _make_image_heavy_pdf(path: Path, *, width: int = 2400, height: int = 3200) -> Path:
    """Embed a large RGB image so lossless deflate barely helps vs lossy JPEG."""
    # Low-periodicity samples so Flate stays large; JPEG+downsample wins.
    samples = bytearray(width * height * 3)
    for i in range(0, len(samples), 3):
        samples[i] = (i * 17 + (i >> 8)) % 256
        samples[i + 1] = (i * 31 + (i >> 4)) % 256
        samples[i + 2] = (i * 47 + i) % 256
    pix = fitz.Pixmap(fitz.csRGB, width, height, bytes(samples), 0)
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, pixmap=pix)
        doc.save(str(path), deflate=False)
        return path
    finally:
        doc.close()


def test_compress_never_overwrites_source(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = file_sha256(src)
    with pytest.raises(SourceOverwriteError):
        ops.compress_pdf(str(src), str(src))
    assert file_sha256(src) == source_hash


def test_compress_smoke_openable_and_source_unchanged(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="compress me " * 40)
    source_hash = file_sha256(src)
    out = tmp_path / "out.pdf"
    ops.compress_pdf(str(src), str(out), profile="lossless")
    assert file_sha256(src) == source_hash
    assert out.is_file()
    assert out.stat().st_size <= src.stat().st_size
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 1
        assert "compress" in doc[0].get_text()
    finally:
        doc.close()


def test_compress_lossy_screen_shrinks_image_heavy(tmp_path: Path) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf")
    source_hash = file_sha256(src)
    lossless_out = tmp_path / "lossless.pdf"
    lossy_out = tmp_path / "screen.pdf"
    ops.compress_pdf(str(src), str(lossless_out), profile="lossless")
    ops.compress_pdf(str(src), str(lossy_out), profile="screen")
    assert file_sha256(src) == source_hash
    assert lossy_out.stat().st_size < lossless_out.stat().st_size
    assert lossy_out.stat().st_size < src.stat().st_size
    with fitz.open(str(lossy_out)) as doc:
        assert doc.page_count == 1
        assert doc[0].get_images()


def test_compress_job_handler_accepts_lossy_profile_params(tmp_path: Path) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf")
    source_hash = file_sha256(src)
    out = tmp_path / "job_out.pdf"
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_optimize_secure_handlers(runner)
        runner.run(
            JobSpec.create(
                "compress",
                inputs=[str(src)],
                output=str(out),
                options={
                    "profile": "screen",
                    "dpi": 72,
                    "jpeg_quality": 40,
                    "dpi_threshold": 100,
                },
            )
        )
    finally:
        temp.cleanup()
    assert file_sha256(src) == source_hash
    assert out.is_file()
    assert out.stat().st_size < src.stat().st_size
    with fitz.open(str(out)) as doc:
        assert doc.page_count == 1


def test_repair_rewrite_surfaces_is_repaired(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = file_sha256(src)
    out = tmp_path / "repaired.pdf"
    result = ops.repair_pdf(str(src), str(out))
    assert result.output_path == str(out)
    assert isinstance(result.was_repaired, bool)
    # Clean synthetic PDFs are typically not repaired.
    assert result.was_repaired is False
    assert file_sha256(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 1
    finally:
        doc.close()


def test_encrypt_round_trip_and_wrong_password(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="classified")
    source_hash = file_sha256(src)
    enc = tmp_path / "enc.pdf"
    ops.encrypt_pdf(
        str(src),
        str(enc),
        user_password="user-secret",
        owner_password="owner-secret",
        permissions=ops.PdfPermissions(allow_print=True, allow_copy=False),
    )
    assert file_sha256(src) == source_hash

    locked = fitz.open(str(enc))
    try:
        assert locked.needs_pass
        assert locked.authenticate("wrong") == 0
        assert locked.authenticate("user-secret") != 0
        assert "classified" in locked[0].get_text()
    finally:
        locked.close()

    dec = tmp_path / "dec.pdf"
    ops.decrypt_pdf(str(enc), str(dec), password="user-secret")
    unlocked = fitz.open(str(dec))
    try:
        assert not unlocked.needs_pass
        assert "classified" in unlocked[0].get_text()
    finally:
        unlocked.close()
    assert file_sha256(src) == source_hash


def test_encrypt_rejects_empty_password(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    with pytest.raises(ValueError, match="user_password"):
        ops.encrypt_pdf(str(src), str(tmp_path / "out.pdf"), user_password="")


def test_sanitize_metadata_and_optional_annotations(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), "keep text", fontsize=18)
        page.add_highlight_annot(fitz.Rect(30, 60, 120, 90))
        doc.set_metadata(
            {"title": "Drop Me", "author": "Secret", "subject": "subj", "keywords": "k"}
        )
        doc.set_xml_metadata("<x:xmpmeta xmlns:x='adobe:ns:meta/'/>")
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = file_sha256(src)

    meta_only = tmp_path / "meta.pdf"
    ops.sanitize_pdf(str(src), str(meta_only), strip_annotations=False)
    assert file_sha256(src) == source_hash
    cleaned = metadata_get(str(meta_only))
    assert cleaned.get("title") in ("", None)
    assert cleaned.get("author") in ("", None)
    with fitz.open(str(meta_only)) as out:
        assert out.get_xml_metadata() in ("", None)
        assert list(out[0].annots() or [])  # annotations kept

    scrubbed = tmp_path / "scrubbed.pdf"
    ops.sanitize_pdf(str(src), str(scrubbed), strip_annotations=True)
    with fitz.open(str(scrubbed)) as out:
        assert list(out[0].annots() or []) == []
        assert "keep text" in out[0].get_text()
    assert file_sha256(src) == source_hash


def test_sanitize_cancel_mid_annot_loop_cleans_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel while stripping annotations must not promote and must scrub staging."""
    from pagedrop.core.jobs import CancelToken, JobCancelledError

    src = tmp_path / "multi.pdf"
    doc = fitz.open()
    try:
        for i in range(5):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"page {i}", fontsize=14)
            page.add_highlight_annot(fitz.Rect(30, 60, 120, 90))
        doc.save(str(src))
    finally:
        doc.close()
    src_hash = file_sha256(src)
    out = tmp_path / "sanitized.pdf"
    token = CancelToken()
    checks = {"n": 0}
    real_check = ops._check_cancel

    def counting_check(cancel):
        checks["n"] += 1
        if checks["n"] >= 2:
            token.cancel()
        real_check(cancel)

    monkeypatch.setattr(ops, "_check_cancel", counting_check)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_optimize_secure_handlers(runner)
        with pytest.raises(JobCancelledError):
            runner.run(
                JobSpec.create(
                    "sanitize",
                    inputs=[str(src)],
                    output=out,
                    options={
                        "strip_metadata": True,
                        "strip_xmp": True,
                        "strip_annotations": True,
                    },
                ),
                cancel=token,
            )
        assert not out.exists()
        assert not any(temp._dir.glob("job_*"))
        assert file_sha256(src) == src_hash
    finally:
        temp.cleanup()


def test_fix_page_size_covered_by_phase24(tmp_path: Path) -> None:
    """Phase 27 reuses Phase 24 normalize — not a second implementation."""
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = file_sha256(src)
    out = tmp_path / "sized.pdf"
    normalize_pdf_page_size(str(src), str(out), 300, 400, strategy="fit")
    assert file_sha256(src) == source_hash
    with fitz.open(str(out)) as doc:
        rect = doc[0].rect
        assert abs(rect.width - 300) < 0.5
        assert abs(rect.height - 400) < 0.5


# --- Lossy compress runs in an owned child process ----------------------------

_SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


class _ChildSpy:
    """Wraps ``popen_owned``: records spawns, argv, kwargs and FITZ_LOCK state."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, argv: list[str] | None = None) -> None:
        self.procs: list[subprocess.Popen[str]] = []
        self.argvs: list[list[str]] = []
        self.kwargs: list[dict[str, object]] = []
        self.lock_owned: list[bool] = []
        self.on_spawn = lambda: None
        real = ops.popen_owned

        def spawn(spawn_argv: list[str], **kwargs: object) -> subprocess.Popen[str]:
            self.argvs.append(list(spawn_argv))
            self.kwargs.append(kwargs)
            self.lock_owned.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
            proc = real(argv if argv is not None else spawn_argv, **kwargs)
            self.procs.append(proc)
            self.on_spawn()
            return proc

        monkeypatch.setattr(ops, "popen_owned", spawn)


def _compress_runner(temp: TempManager) -> SerializedJobRunner:
    runner = SerializedJobRunner(temp)
    register_optimize_secure_handlers(runner)
    return runner


def _compress_spec(src: Path, out: Path, profile: str = "screen") -> JobSpec:
    return JobSpec.create(
        "compress", inputs=[str(src)], output=str(out), options={"profile": profile}
    )


def test_compress_handler_registration_and_lossy_job_runs_in_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf", width=1200, height=1600)
    before = file_sha256(src)
    out = tmp_path / "small.pdf"
    spy = _ChildSpy(monkeypatch)
    in_process: list[bool] = []
    real_compress = ops.compress_pdf
    monkeypatch.setattr(
        ops,
        "compress_pdf",
        lambda *a, **k: in_process.append(True) or real_compress(*a, **k),
    )
    temp = TempManager()
    try:
        runner = _compress_runner(temp)
        assert runner._handlers["compress"].holds_fitz is False
        assert runner._handlers["repair"].holds_fitz is True
        runner.run(_compress_spec(src, out))
    finally:
        temp.cleanup()
    assert file_sha256(src) == before
    assert out.is_file() and out.resolve() != src.resolve()
    assert out.stat().st_size < src.stat().st_size
    with fitz.open(str(out)) as doc:
        assert doc.page_count == 1 and doc[0].get_images()
    assert len(spy.procs) == 1 and spy.procs[0].returncode == 0
    assert spy.lock_owned == [False], "FITZ_LOCK held while waiting on the child"
    assert not in_process, "lossy compress ran in the GUI process"


def test_compress_lossy_password_goes_over_stdin_not_argv_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = _make_image_heavy_pdf(tmp_path / "plain.pdf", width=1200, height=1600)
    locked = tmp_path / "locked.pdf"
    ops.encrypt_pdf(str(plain), str(locked), user_password="s3cret-pw")
    before = file_sha256(locked)
    out = tmp_path / "small.pdf"
    spy = _ChildSpy(monkeypatch)
    creds = RuntimeCredentials()
    creds.set(locked, "s3cret-pw")
    temp = TempManager()
    try:
        _compress_runner(temp).run(_compress_spec(locked, out), credentials=creds)
    finally:
        temp.cleanup()
    assert file_sha256(locked) == before
    assert out.resolve() != locked.resolve()
    with fitz.open(str(out)) as doc:
        # Same as the in-process path: the rewrite of an unlocked doc is written open.
        assert not doc.needs_pass
        assert doc.page_count == 1 and doc[0].get_images()
    assert out.stat().st_size < locked.stat().st_size
    assert all("s3cret-pw" not in arg for argv in spy.argvs for arg in argv)
    assert not any(
        "s3cret-pw" in value
        for kwargs in spy.kwargs
        for value in (kwargs.get("env") or {}).values()
    )


def test_compress_lossy_wrong_password_reports_typed_error_without_secret(
    tmp_path: Path,
) -> None:
    plain = _make_image_heavy_pdf(tmp_path / "plain.pdf", width=600, height=800)
    locked = tmp_path / "locked.pdf"
    ops.encrypt_pdf(str(plain), str(locked), user_password="right-pw")
    creds = RuntimeCredentials()
    creds.set(locked, "wrong-pw")
    out = tmp_path / "out.pdf"
    temp = TempManager()
    try:
        with pytest.raises(ops.CompressWorkerError, match="PdfPasswordError") as excinfo:
            _compress_runner(temp).run(_compress_spec(locked, out), credentials=creds)
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()
    assert isinstance(excinfo.value, JobError)
    assert "wrong-pw" not in str(excinfo.value)
    assert not out.exists()


def test_compress_lossy_cancel_kills_child_and_leaves_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf", width=600, height=800)
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    token = CancelToken()
    spy = _ChildSpy(monkeypatch, argv=_SLEEPER)
    spy.on_spawn = token.cancel  # cancel right after the child exists
    temp = TempManager()
    try:
        with pytest.raises(JobCancelledError):
            _compress_runner(temp).run(_compress_spec(src, out), cancel=token)
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()
    assert len(spy.procs) == 1 and spy.procs[0].poll() is not None, "child still running"
    assert not out.exists()
    assert file_sha256(src) == before


def test_compress_lossy_child_crash_raises_typed_error_with_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf", width=600, height=800)
    out = tmp_path / "out.pdf"
    crash = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('mupdf exploded'); sys.exit(3)",
    ]
    _ChildSpy(monkeypatch, argv=crash)
    temp = TempManager()
    try:
        with pytest.raises(ops.CompressWorkerError, match="mupdf exploded"):
            _compress_runner(temp).run(_compress_spec(src, out))
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()
    assert not out.exists()


def test_compress_lossy_child_exit_without_output_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf", width=600, height=800)
    _ChildSpy(monkeypatch, argv=[sys.executable, "-c", "pass"])
    with pytest.raises(ops.CompressWorkerError, match="without writing output"):
        ops.compress_pdf_lossy_in_child(
            str(src), str(tmp_path / "out.pdf"), ops.resolve_lossy_profile("screen")
        )


def test_compress_lossy_crash_detail_redacts_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    echo = [sys.executable, "-c", "import sys; sys.stderr.write(sys.stdin.read()); sys.exit(1)"]
    _ChildSpy(monkeypatch, argv=echo)
    with pytest.raises(ops.CompressWorkerError) as excinfo:
        ops.compress_pdf_lossy_in_child(
            str(src),
            str(tmp_path / "out.pdf"),
            ops.resolve_lossy_profile("screen"),
            password="hunter2-secret",
        )
    assert "hunter2-secret" not in str(excinfo.value)
    assert "source" in str(excinfo.value)  # the payload echo proves stdin was read


def test_compress_lossy_timeout_kills_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    spy = _ChildSpy(monkeypatch, argv=_SLEEPER)
    with pytest.raises(ops.CompressWorkerError, match="timed out"):
        ops.compress_pdf_lossy_in_child(
            str(src),
            str(tmp_path / "out.pdf"),
            ops.resolve_lossy_profile("screen"),
            timeout=0.3,
        )
    assert spy.procs[0].poll() is not None
    assert ops.COMPRESS_WORKER_TIMEOUT_S >= 600


def test_compress_lossy_in_child_rejects_source_as_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    before = file_sha256(src)
    spy = _ChildSpy(monkeypatch)
    with pytest.raises(SourceOverwriteError):
        ops.compress_pdf_lossy_in_child(
            str(src), str(src), ops.resolve_lossy_profile("screen")
        )
    assert spy.procs == []
    assert file_sha256(src) == before


def test_compress_lossless_job_holds_fitz_lock_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="lossless " * 30)
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    spy = _ChildSpy(monkeypatch)
    owned: list[bool] = []
    real_compress = ops.compress_pdf

    def watching(*args: object, **kwargs: object) -> None:
        owned.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_compress(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ops, "compress_pdf", watching)
    temp = TempManager()
    try:
        _compress_runner(temp).run(_compress_spec(src, out, "lossless"))
    finally:
        temp.cleanup()
    assert owned == [True]
    assert spy.procs == []
    assert file_sha256(src) == before
    assert out.is_file() and out.resolve() != src.resolve()


def test_compress_worker_argv_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ops.compress_worker_argv()[-3:] == [
        "-m",
        "pagedrop.core.optimize_secure",
        "--compress-json",
    ]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert ops.compress_worker_argv() == [
        sys.executable,
        ops.COMPRESS_WORKER_FLAG,
        "--compress-json",
    ]
