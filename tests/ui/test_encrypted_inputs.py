"""Every PDF-input tool page works on a password-protected source.

Each case drops an encrypted PDF into a real tool page, runs it through the real
job pipeline and checks that the password was asked for exactly once, the job
succeeded, the source is untouched and the output is a valid, different file.
Only external engines (Tesseract, openpyxl, LibreOffice) are stubbed, so the
password still has to reach the core call for the job to succeed.
"""

from __future__ import annotations

import contextlib
import json
import types
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import pytest
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
)

from pagedrop.core import capabilities, native_conversions, pdf_tools
from pagedrop.core.capabilities import (
    OPENPYXL,
    TESSDATA,
    CapabilityStatus,
    clear_cache,
)
from pagedrop.core.native_conversions import batch_output_paths
from pagedrop.ui.modify_tools_shell import open_modify_shell
from pagedrop.ui.native_convert_shell import open_conversion_shell
from pagedrop.ui.ocr_shell import open_ocr_shell
from pagedrop.ui.optimize_secure_shell import open_optimize_secure_shell
from pagedrop.ui.organize_shell import open_organize_shell
from pagedrop.ui.pdf_to_word_shell import open_pdf_to_word_shell
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.watermark_preview import WatermarkPreviewCanvas
from pagedrop.ui.tools_window import ToolsWindow
from tests.conftest import file_sha256
from tests.ui.test_tool_shell import _count_password_prompts

PASSWORD = "secret"
PAGES = 4  # P0 (with a table), P1 (highlighted), blank, P3


@pytest.fixture(autouse=True)
def _fresh_capabilities():
    clear_cache()
    yield
    clear_cache()


def _build_pdf(path: Path, *, password: str | None) -> None:
    """Four 300x300 pages with a table, a highlight, bookmarks and an attachment."""
    doc = fitz.open()
    try:
        for i in range(PAGES):
            page = doc.new_page(width=300, height=300)
            if i == 2:
                continue
            page.insert_text((40, 40), f"P{i}", fontsize=18)
            if i == 0:
                for r in range(3):
                    for c in range(2):
                        cell = fitz.Rect(
                            40 + c * 80, 80 + r * 30, 120 + c * 80, 110 + r * 30
                        )
                        page.draw_rect(cell, color=(0, 0, 0), width=1)
                        page.insert_text((cell.x0 + 6, cell.y1 - 10), f"r{r}c{c}", fontsize=10)
            if i == 1:
                page.add_highlight_annot(page.search_for("P1")[0])
        doc.set_toc([[1, "Intro", 1], [1, "Two", 2]])
        doc.embfile_add("readme.txt", b"hello")
        doc.set_metadata({"title": "Original", "author": "Alice"})
        if password is None:
            doc.save(str(path))
        else:
            doc.save(
                str(path),
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw=password,
                owner_pw="owner",
            )
    finally:
        doc.close()


@contextlib.contextmanager
def _opened(path: Path, password: str | None = None):
    doc = fitz.open(str(path))
    try:
        if password is None:
            assert not doc.needs_pass, f"{path.name} is still password-protected"
        else:
            assert doc.needs_pass and doc.authenticate(password)
        yield doc
    finally:
        doc.close()


def _text(doc: fitz.Document, index: int) -> str:
    return doc[index].get_text()


@dataclass
class Env:
    tmp: Path
    monkeypatch: pytest.MonkeyPatch
    src: Path
    plain: Path
    qtbot: object = None
    shell: ToolShellWindow | None = None
    round: int = 0
    seen: dict = field(default_factory=dict)

    def out(self, name: str) -> Path:
        folder = self.tmp / f"out{self.round}"
        folder.mkdir(exist_ok=True)
        return folder / name

    @property
    def folder(self) -> Path:
        return self.out("x").parent

    def pick(self, target: str, value: Path | str) -> None:
        self.monkeypatch.setattr(target, lambda *a, **k: str(value))

    def pick_dir(self) -> None:
        self.monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(self.folder)
        )

    def edits(self) -> list[QLineEdit]:
        return [
            edit
            for edit in self.shell._options_host.findChildren(QLineEdit)
            if edit.objectName() != "qt_spinbox_lineedit"
        ]

    def combo(self, data: str) -> QComboBox:
        for box in self.shell._options_host.findChildren(QComboBox):
            if box.findData(data) >= 0:
                box.setCurrentIndex(box.findData(data))
                return box
        raise AssertionError(f"no combo offers {data!r}")


@dataclass(frozen=True)
class Case:
    id: str
    open: Callable[[ToolsWindow], ToolShellWindow | None]
    setup: Callable[[Env], Path]
    check: Callable[[Env, Path], None]
    drop: Callable[[Env], list[Path]] = lambda env: [env.src]
    engine: Callable[[Env], None] | None = None
    prompts: int = 1


def _pages(n: int, *, texts: dict[int, str] | None = None):
    """Check: output opens unencrypted with *n* pages and the given page texts."""

    def check(env: Env, out: Path) -> None:
        with _opened(out) as doc:
            assert doc.page_count == n
            for index, text in (texts or {}).items():
                assert text in _text(doc, index)

    return check


def _file_setup(picker: str, name: str, configure=None):
    def setup(env: Env) -> Path:
        out = env.out(name)
        env.pick(picker, out)
        if configure is not None:
            configure(env)
        return out

    return setup


ORG = "pagedrop.ui.organize_shell._pick_save_pdf"
MOD = "pagedrop.ui.modify_tools_shell._pick_save_path"
OPT = "pagedrop.ui.optimize_secure_shell._pick_save_path"
OCR = "pagedrop.ui.ocr_shell._pick_save_path"
NAT = "pagedrop.ui.native_convert_shell._pick_save_path"
WORD = "pagedrop.ui.pdf_to_word_shell._pick_save_path"


def _org(tool_id: str):
    return lambda tools: open_organize_shell(tools, tool_id)


def _mod(tool_id: str):
    return lambda tools: open_modify_shell(tools, tool_id)


def _opt(tool_id: str):
    return lambda tools: open_optimize_secure_shell(tools, tool_id)


def _ocr(tool_id: str):
    return lambda tools: open_ocr_shell(tools, tool_id)


def _simple(case_id, opener, picker, suffix, check, *, configure=None, **kw) -> Case:
    return Case(
        case_id,
        opener,
        _file_setup(picker, f"locked_{suffix}.pdf", configure),
        check,
        **kw,
    )


# --- organize ----------------------------------------------------------------


def _split_setup(env: Env) -> Path:
    env.shell._ranges_edit.setText("1-2")
    env.shell._folder_edit.setText(str(env.folder))
    return pdf_tools.predicted_range_output_paths(
        [(0, 1)], env.folder, base_name=env.src.stem
    )[0]


def _alternate_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES + 2
        assert "P0" in _text(doc, 0) and "B0" in _text(doc, 1)
        assert "P1" in _text(doc, 2) and "B1" in _text(doc, 3)


def _zip_setup(env: Env) -> Path:
    out = env.out("pdfs.zip")
    env.pick("pagedrop.ui.organize_shell._pick_save_zip", out)
    return out


def _zip_check(env: Env, out: Path) -> None:
    with zipfile.ZipFile(out) as archive:
        assert sorted(archive.namelist()) == ["locked.pdf", "plain.pdf"]
        # The raw encrypted bytes are packed as they are.
        assert archive.read("locked.pdf") == env.src.read_bytes()


def _labels_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert doc[0].get_label() == "X-1"
        assert doc[3].get_label() == "X-4"


def _page_labels_configure(env: Env) -> None:
    env.edits()[0].setText("X-")


def _normalize_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert all(abs(p.rect.width - 595) < 1 and abs(p.rect.height - 842) < 1 for p in doc)


def _metadata_setup(*, strip: bool):
    def setup(env: Env) -> Path:
        if env.round == 0:
            # Dropping the file already read the title through the unlocked source.
            assert env.edits()[0].text() == "Original"
        out = env.out("locked_metadata.pdf")
        env.pick(ORG, out)
        if strip:
            for box in env.shell._options_host.findChildren(QCheckBox):
                box.setChecked(True)
        else:
            env.edits()[0].setText("New title")
        return out

    return setup


def _metadata_check(*, strip: bool):
    def check(env: Env, out: Path) -> None:
        with _opened(out) as doc:
            assert doc.page_count == PAGES
            if strip:
                assert not doc.metadata.get("title")
                assert not doc.metadata.get("author")
            else:
                assert doc.metadata["title"] == "New title"
                assert doc.metadata["author"] == "Alice"

    return check


def _attachments_setup(action: str):
    def setup(env: Env) -> Path:
        env.combo(action)
        name, *_ = env.edits()
        if action == "extract":
            env.monkeypatch.setattr(
                "pagedrop.ui.organize_shell._pick_folder",
                lambda *a, **k: str(env.folder),
            )
            return env.folder / "locked_attachments.zip"
        out = env.out("locked_attachments.pdf")
        env.pick(ORG, out)
        if action == "add":
            extra = env.tmp / "note.txt"
            extra.write_text("hi", encoding="utf-8")
            name.setText("note.txt")
            env.edits()[1].setText(str(extra))
        else:
            name.setText("readme.txt")
        return out

    return setup


def _attachments_check(action: str):
    def check(env: Env, out: Path) -> None:
        if action == "extract":
            with zipfile.ZipFile(out) as archive:
                assert archive.read("readme.txt") == b"hello"
            return
        with _opened(out) as doc:
            assert doc.page_count == PAGES
            names = doc.embfile_names()
            if action == "add":
                assert sorted(names) == ["note.txt", "readme.txt"]
            else:
                assert names == []

    return check


# --- modify ------------------------------------------------------------------


def _crop_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert doc[0].cropbox.width == pytest.approx(300 - 72)


def _watermark_configure(env: Env) -> None:
    # The live preview renders the unlocked page too; a failed render only warns.
    canvas = env.shell.findChild(WatermarkPreviewCanvas)
    env.qtbot.waitUntil(lambda: not canvas._page_pix.isNull(), timeout=10_000)


def _watermark_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert "P0" in _text(doc, 0)
        # A rotated text watermark is stamped as an image on every page.
        assert all(len(page.get_images()) == 1 for page in doc)


def _header_footer_configure(env: Env) -> None:
    header, footer = env.edits()[:2]
    header.setText("HDRTEXT")
    footer.setText("FTRTEXT")


def _bates_batch_setup(env: Env) -> Path:
    env.pick_dir()
    return batch_output_paths(
        [str(env.src), str(env.plain)], env.folder, "_bates.pdf"
    )[0]


def _bates_batch_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert "000001" in _text(doc, 0)
    with _opened(out.with_name("plain_bates.pdf")) as doc:
        assert "000005" in _text(doc, 0)


def _bookmarks_setup(action: str):
    def setup(env: Env) -> Path:
        # Dropping the file already read its bookmarks through the unlocked source.
        editor = env.shell._options_host.findChild(QPlainTextEdit)
        if env.round == 0:
            assert editor.toPlainText() == "1|Intro|1\n1|Two|2"
        env.combo(action)
        if action == "set":
            editor.setPlainText("1|Alpha|1")
        out = env.out("locked_bookmarks.pdf")
        env.pick(MOD, out)
        return out

    return setup


def _bookmarks_check(action: str):
    def check(env: Env, out: Path) -> None:
        with _opened(out) as doc:
            toc = doc.get_toc()
            if action == "set":
                assert doc.page_count == PAGES
                assert toc == [[1, "Alpha", 1]]
            elif action == "pages":
                assert doc.page_count == PAGES
                assert len(toc) == PAGES
            elif action == "clear":
                assert doc.page_count == PAGES
                assert toc == []
            else:
                assert doc.page_count == PAGES + 1
                assert "Intro" in _text(doc, 0)

    return check


def _annotations_setup(action: str):
    def configure(env: Env) -> None:
        env.combo(action)

    return _file_setup(MOD, "locked_annotations.pdf", configure)


def _annotations_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert not list(doc[1].annots())
        assert "P1" in _text(doc, 1)


_blank_check = _pages(PAGES - 1, texts={0: "P0", 1: "P1", 2: "P3"})


# --- optimize and secure -----------------------------------------------------


def _encrypt_configure(env: Env) -> None:
    shell = env.shell
    shell._encrypt_user_pw.setText("newpw")
    shell._encrypt_confirm_pw.setText("newpw")


def _encrypt_check(env: Env, out: Path) -> None:
    with _opened(out, "newpw") as doc:
        assert doc.page_count == PAGES
        assert "P3" in _text(doc, 3)


def _sanitize_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert not doc.metadata.get("title")


def _compress_lossy_configure(env: Env) -> None:
    env.combo("screen")


# --- OCR, tables and Office engines (stubbed) --------------------------------


def _stub_tessdata(env: Env) -> None:
    data = env.tmp / "tessdata"
    data.mkdir()
    (data / "eng.traineddata").write_bytes(b"x")
    status = CapabilityStatus(
        id=TESSDATA,
        available=True,
        extras={"path": str(data), "languages": ["eng"]},
    )
    env.monkeypatch.setitem(capabilities._PROBES, TESSDATA, lambda: status)
    clear_cache()
    env.seen["ocr_pages"] = []

    def fake_pdfocr(pixmap, *args, **kwargs):
        # Rendering this pixmap needed the unlocked page; only Tesseract is faked.
        env.seen["ocr_pages"].append((pixmap.width, pixmap.height))
        page = fitz.open()
        try:
            page.new_page(width=300, height=300).insert_text((20, 40), "OCRTXT")
            return page.tobytes()
        finally:
            page.close()

    env.monkeypatch.setattr(fitz.Pixmap, "pdfocr_tobytes", fake_pdfocr)


def _ocr_check(env: Env, out: Path) -> None:
    with _opened(out) as doc:
        assert doc.page_count == PAGES
        assert "OCRTXT" in _text(doc, 0)
    assert len(env.seen["ocr_pages"]) == PAGES * (env.round + 1)


def _tables_setup(format_id: str, name: str):
    def setup(env: Env) -> Path:
        env.combo(format_id)
        out = env.out(name)
        env.pick(OCR, out)
        return out

    return setup


def _csv_check(env: Env, out: Path) -> None:
    assert out.read_text(encoding="utf-8").splitlines() == [
        "r0c0,r0c1",
        "r1c0,r1c1",
        "r2c0,r2c1",
    ]


def _tables_json_check(env: Env, out: Path) -> None:
    assert "r2c1" in out.read_text(encoding="utf-8")


def _stub_openpyxl(env: Env) -> None:
    env.monkeypatch.setitem(
        capabilities._PROBES,
        OPENPYXL,
        lambda: CapabilityStatus(id=OPENPYXL, available=True),
    )
    clear_cache()
    real_soft_import = native_conversions.soft_import
    rows: list[list[str]] = []
    env.seen["xlsx_rows"] = rows

    class Sheet:
        title = ""

        def append(self, row):
            rows.append(list(row))

    class Workbook:
        active = Sheet()

        def save(self, path):
            Path(path).write_bytes(b"PK\x03\x04" + json.dumps(rows).encode())

    fake = types.SimpleNamespace(Workbook=Workbook)
    env.monkeypatch.setattr(
        native_conversions,
        "soft_import",
        lambda name: (fake, None) if name == "openpyxl" else real_soft_import(name),
    )


def _xlsx_check(env: Env, out: Path) -> None:
    assert out.read_bytes().startswith(b"PK")
    assert env.seen["xlsx_rows"] == [
        ["r0c0", "r0c1"],
        ["r1c0", "r1c1"],
        ["r2c0", "r2c1"],
    ]


def _stub_libreoffice(env: Env) -> None:
    env.monkeypatch.setattr(
        "pagedrop.ui.pdf_to_word_shell.probe",
        lambda _cid, refresh=False: CapabilityStatus(
            id=capabilities.LIBREOFFICE, available=True, extras={"path": "/bin/soffice"}
        ),
    )
    env.seen["converted"] = []

    def fake_convert(source, output, **_kwargs):
        source = Path(source)
        with _opened(source) as doc:  # the converter is handed an unlocked copy
            env.seen["converted"].append((source, doc.page_count, _text(doc, 0)))
        Path(output).write_bytes(b"PK\x03\x04fake-docx")
        return Path(output)

    env.monkeypatch.setattr(
        "pagedrop.core.pdf_to_docx_jobs.convert_pdf_to_docx", fake_convert
    )


def _word_check(env: Env, out: Path) -> None:
    assert out.read_bytes().startswith(b"PK")
    source, page_count, text = env.seen["converted"][-1]
    assert source != env.src and page_count == PAGES and "P0" in text
    # The temporary decrypted copy is deleted after the job.
    assert not source.exists()


def _export_setup(format_id: str):
    def setup(env: Env) -> Path:
        env.combo(format_id)
        if format_id == "png":
            env.monkeypatch.setattr(
                "pagedrop.ui.native_convert_shell._pick_folder",
                lambda *a, **k: str(env.folder),
            )
            return native_conversions.predicted_export_paths(
                env.folder / "locked.png", format_id="png", pages=list(range(PAGES))
            )[0]
        out = env.out("locked.txt")
        env.pick(NAT, out)
        return out

    return setup


def _export_check(format_id: str):
    def check(env: Env, out: Path) -> None:
        if format_id == "png":
            assert out.read_bytes().startswith(b"\x89PNG")
            assert len(list(out.parent.glob("*.png"))) == PAGES
        else:
            assert "P0" in out.read_text(encoding="utf-8")

    return check


CASES: list[Case] = [
    # Organize
    _simple("reverse", _org("reverse"), ORG, "reversed",
            _pages(PAGES, texts={0: "P3", 3: "P0"})),
    Case("split", _org("split"), _split_setup,
         _pages(2, texts={0: "P0", 1: "P1"})),
    _simple("alternate", _org("alternate"), ORG, "alternated", _alternate_check,
            drop=lambda env: [env.src, env.plain]),
    _simple("n_up", _org("n_up"), ORG, "nup", _pages(1)),
    _simple("booklet", _org("booklet"), ORG, "booklet", _pages(PAGES // 2)),
    _simple("posterize", _org("posterize"), ORG, "poster", _pages(PAGES * 4)),
    _simple("divide", _org("divide"), ORG, "divided", _pages(PAGES * 2)),
    _simple("combine", _org("combine"), ORG, "long", _pages(1)),
    _simple("normalize", _org("normalize"), ORG, "normalized", _normalize_check),
    _simple("page_labels", _org("page_labels"), ORG, "labels", _labels_check,
            configure=_page_labels_configure),
    Case("zip", _org("zip"), _zip_setup, _zip_check,
         drop=lambda env: [env.src, env.plain], prompts=0),
    Case("metadata-set", _org("metadata"), _metadata_setup(strip=False),
         _metadata_check(strip=False)),
    Case("metadata-strip", _org("metadata"), _metadata_setup(strip=True),
         _metadata_check(strip=True)),
    Case("attachments-add", _org("attachments"), _attachments_setup("add"),
         _attachments_check("add")),
    Case("attachments-remove", _org("attachments"), _attachments_setup("remove"),
         _attachments_check("remove")),
    Case("attachments-extract", _org("attachments"), _attachments_setup("extract"),
         _attachments_check("extract")),
    # Modify
    _simple("crop", _mod("crop"), MOD, "cropped", _crop_check),
    _simple("watermark", _mod("watermark"), MOD, "watermarked", _watermark_check,
            configure=_watermark_configure),
    _simple("header_footer", _mod("header_footer"), MOD, "hf",
            _pages(PAGES, texts={0: "HDRTEXT", 3: "FTRTEXT"}),
            configure=_header_footer_configure),
    _simple("page_numbers", _mod("page_numbers"), MOD, "numbered",
            _pages(PAGES, texts={0: "1 / 4", 3: "4 / 4"})),
    _simple("bates-single", _mod("bates"), MOD, "bates",
            _pages(PAGES, texts={0: "000001", 3: "000004"})),
    Case("bates-batch", _mod("bates"), _bates_batch_setup, _bates_batch_check,
         drop=lambda env: [env.src, env.plain]),
    Case("bookmarks-set", _mod("bookmarks"), _bookmarks_setup("set"),
         _bookmarks_check("set")),
    Case("bookmarks-pages", _mod("bookmarks"), _bookmarks_setup("pages"),
         _bookmarks_check("pages")),
    Case("bookmarks-clear", _mod("bookmarks"), _bookmarks_setup("clear"),
         _bookmarks_check("clear")),
    Case("bookmarks-toc_page", _mod("bookmarks"), _bookmarks_setup("toc_page"),
         _bookmarks_check("toc_page")),
    Case("annotations-remove", _mod("annotations"), _annotations_setup("remove"),
         _annotations_check),
    Case("annotations-flatten", _mod("annotations"), _annotations_setup("flatten"),
         _annotations_check),
    _simple("blank_pages", _mod("blank_pages"), MOD, "no_blanks", _blank_check),
    _simple("color_effects", _mod("color_effects"), MOD, "color",
            _pages(PAGES, texts={0: "P0", 3: "P3"})),
    # Optimize and secure
    _simple("compress-lossless", _opt("compress"), OPT, "compressed",
            _pages(PAGES, texts={0: "P0"})),
    _simple("compress-lossy", _opt("compress"), OPT, "compressed",
            _pages(PAGES, texts={0: "P0"}), configure=_compress_lossy_configure),
    _simple("repair", _opt("repair"), OPT, "repaired",
            _pages(PAGES, texts={0: "P0"})),
    _simple("encrypt", _opt("encrypt"), OPT, "encrypted", _encrypt_check,
            configure=_encrypt_configure),
    _simple("decrypt", _opt("decrypt"), OPT, "decrypted",
            _pages(PAGES, texts={0: "P0", 3: "P3"})),
    _simple("sanitize", _opt("sanitize"), OPT, "sanitized", _sanitize_check),
    # OCR, tables and conversions
    _simple("ocr_pdf", _ocr("ocr_pdf"), OCR, "ocr", _ocr_check, engine=_stub_tessdata),
    Case("extract_tables", _ocr("extract_tables"),
         _tables_setup("tables_json", "locked_tables.json"), _tables_json_check),
    Case("pdf_to_csv", _ocr("pdf_to_csv"), _tables_setup("csv", "locked_tables.csv"),
         _csv_check),
    Case("pdf_to_excel", _ocr("pdf_to_excel"),
         _tables_setup("xlsx", "locked_tables.xlsx"), _xlsx_check,
         engine=_stub_openpyxl),
    Case("export_from_pdf-text", lambda tools: open_conversion_shell(tools, "export_from_pdf"),
         _export_setup("text"), _export_check("text")),
    Case("export_from_pdf-png", lambda tools: open_conversion_shell(tools, "export_from_pdf"),
         _export_setup("png"), _export_check("png")),
    Case("pdf_to_word", open_pdf_to_word_shell,
         _file_setup(WORD, "locked.docx"), _word_check, engine=_stub_libreoffice),
]
CASES_BY_ID = {case.id: case for case in CASES}


def _wait_done(qtbot, shell: ToolShellWindow) -> None:
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=30_000)


def _assert_succeeded(env: Env, expected: Path, check) -> None:
    shell = env.shell
    assert shell._result_bar.isVisible(), shell.statusBar().currentMessage()
    assert shell._result_bar._path == str(expected)
    assert expected.is_file()
    assert expected.resolve() != env.src.resolve()
    check(env, expected)


def _run(qtbot, tmp_path, monkeypatch, case: Case, replies, *, runs: int = 1) -> tuple[Env, list[bool]]:
    src = tmp_path / "locked.pdf"
    plain = tmp_path / "plain.pdf"
    _build_pdf(src, password=PASSWORD)
    doc = fitz.open()
    try:
        for i in range(2):
            doc.new_page(width=300, height=300).insert_text((40, 40), f"B{i}", fontsize=18)
        doc.save(str(plain))
    finally:
        doc.close()
    source_hashes = {p: file_sha256(p) for p in (src, plain)}
    env = Env(tmp_path, monkeypatch, src, plain, qtbot)
    # Qt's warning boxes are stubbed in tests; a tool must not need any of them.
    boxes: list[str] = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(
            QMessageBox,
            name,
            staticmethod(
                lambda *a, **k: boxes.append(str(a[2:3])) or QMessageBox.StandardButton.Ok
            ),
        )
    if case.engine is not None:
        case.engine(env)
    prompts = _count_password_prompts(monkeypatch, replies)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = case.open(tools)
    assert isinstance(shell, ToolShellWindow)
    qtbot.addWidget(shell)
    env.shell = shell

    shell.drop_zone.set_paths([str(p) for p in case.drop(env)])
    for env.round in range(runs):
        expected = case.setup(env)
        shell._run_btn.click()
        _wait_done(qtbot, shell)
        _assert_succeeded(env, expected, case.check)
    assert boxes == []
    for path, digest in source_hashes.items():
        assert file_sha256(path) == digest
    shell.close()
    tools.close()
    return env, prompts


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_encrypted_input_runs_with_one_prompt(
    qtbot, tmp_path, monkeypatch, isolated_settings, case
):
    replies = [(PASSWORD, True)] if case.prompts else []
    _, prompts = _run(qtbot, tmp_path, monkeypatch, case, replies)
    assert prompts == [False] * case.prompts


# One tool per family: a second Run on the same tool page reuses the password.
SECOND_RUN_IDS = [
    "reverse", "metadata-set", "crop", "bookmarks-set", "compress-lossless",
    "ocr_pdf", "export_from_pdf-text", "pdf_to_csv", "pdf_to_word",
]


@pytest.mark.parametrize("case_id", SECOND_RUN_IDS)
def test_second_run_does_not_prompt_again(
    qtbot, tmp_path, monkeypatch, isolated_settings, case_id
):
    _, prompts = _run(
        qtbot, tmp_path, monkeypatch, CASES_BY_ID[case_id], [(PASSWORD, True)], runs=2
    )
    assert prompts == [False]


# Tools that probe the PDF in their own handler or on drop, plus the shared preflight.
RETRY_IDS = [
    "split", "metadata-set", "attachments-extract", "watermark", "bookmarks-set",
    "blank_pages", "export_from_pdf-text", "ocr_pdf", "pdf_to_csv", "compress-lossless",
    "reverse", "decrypt",
]


@pytest.mark.parametrize("case_id", RETRY_IDS)
def test_wrong_password_then_right_password_succeeds(
    qtbot, tmp_path, monkeypatch, isolated_settings, case_id
):
    _, prompts = _run(
        qtbot,
        tmp_path,
        monkeypatch,
        CASES_BY_ID[case_id],
        [("wrong", True), (PASSWORD, True)],
    )
    # The retry says the password was incorrect, and nothing asks a third time.
    assert prompts == [False, True]


def test_compare_prompts_once_for_an_encrypted_original(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    from pagedrop.ui.compare_window import CompareWindow

    locked = tmp_path / "locked.pdf"
    revised = tmp_path / "revised.pdf"
    for path, text, password in (
        (locked, "Original sentence here", PASSWORD),
        (revised, "Revised sentence here", None),
    ):
        doc = fitz.open()
        try:
            doc.new_page(width=612, height=792).insert_text((72, 260), text, fontsize=10)
            if password is None:
                doc.save(str(path))
            else:
                doc.save(
                    str(path),
                    encryption=fitz.PDF_ENCRYPT_AES_256,
                    user_pw=password,
                    owner_pw="owner",
                )
        finally:
            doc.close()
    digests = {p: file_sha256(p) for p in (locked, revised)}
    prompts = _count_password_prompts(monkeypatch, [(PASSWORD, True)])

    window = CompareWindow()
    qtbot.addWidget(window)
    window.show()
    window._row_a.set_text(str(locked))
    window._row_b.set_text(str(revised))
    for _ in range(2):
        window._report = None
        window._run_compare()
        qtbot.waitUntil(lambda: window._report is not None, timeout=10_000)
        qtbot.waitUntil(lambda: not window._comparing, timeout=10_000)
        # The unlocked text is what was compared, not an empty page.
        assert [c.text for c in window._report.changes] == ["Original → Revised"]

    assert prompts == [False]
    for path, digest in digests.items():
        assert file_sha256(path) == digest
    window.close()


def test_decrypt_reports_owner_restricted_pdf_without_prompting(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    src = tmp_path / "restricted.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=300, height=300).insert_text((40, 40), "P0")
        doc.save(
            str(src),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="",
            owner_pw="owner",
            permissions=fitz.PDF_PERM_PRINT,
        )
    finally:
        doc.close()
    digest = file_sha256(src)
    prompts = _count_password_prompts(monkeypatch, [])
    messages: list[str] = []
    monkeypatch.setattr(
        "pagedrop.ui.optimize_secure_shell.QMessageBox.information",
        lambda _parent, _title, text, *a, **k: messages.append(text),
    )
    picked: list[object] = []
    monkeypatch.setattr(
        OPT, lambda *a, **k: picked.append(a) or str(tmp_path / "never.pdf")
    )

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_optimize_secure_shell(tools, "decrypt")
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(src)])
    shell._run_btn.click()

    assert len(messages) == 1
    assert "owner password" in messages[0] and "restricts" in messages[0]
    assert prompts == [] and picked == []
    assert not shell.is_job_running()
    assert not (tmp_path / "never.pdf").exists()
    assert file_sha256(src) == digest
    shell.close()
    tools.close()
