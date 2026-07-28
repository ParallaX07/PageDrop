"""Optimize & Secure PDF helpers (Phase 27 + Phase 31 lossy compress).

Lossless compress, repair/rewrite, encrypt/decrypt, permissions, and sanitize —
PyMuPDF only. Outputs are always new paths (never the source).

Save profiles → ``Document.save`` / ``ez_save`` knobs
-----------------------------------------------------

=======  =======  =====  =======  ===============  =============  ===========
Profile  garbage  clean  deflate  deflate_images   deflate_fonts  use_objstms
=======  =======  =====  =======  ===============  =============  ===========
fast     1        False  True     False            False          False
lossless 3        True   True     True             True           True
max      4        True   True     True             True           True
=======  =======  =====  =======  ===============  =============  ===========

- **fast** — light garbage collection; deflate content streams only (quick rewrite).
- **lossless** — same defaults as PyMuPDF ``Document.ez_save`` (garbage=3, clean,
  full deflate, object streams). Preferred compress profile.
- **max** — fullest GC (garbage=4) plus the lossless clean/deflate stack; used by
  repair rewrites.

``garbage`` levels (MuPDF): 0 none, 1 unused objects, 2 compact xref, 3 duplicate
streams, 4 (max) also recursively remove unused. ``clean`` rewrites content
streams; ``deflate*`` zlib-compress streams/images/fonts.

Lossy compress presets → ``Document.rewrite_images`` then lossless save
-----------------------------------------------------------------------

=======  ===  =============  ==============  ==========
Preset   DPI  JPEG quality   dpi_threshold   dpi_target
=======  ===  =============  ==============  ==========
screen   72   50             100             72
ebook    150  70             200             150
print    300  85             400             300
=======  ===  =============  ==============  ==========

- **screen** — on-screen reading; aggressive downsample + JPEG (quality can drop).
- **ebook** — tablets / e-readers; moderate downsample + JPEG.
- **print** — print-ish; light downsample + higher JPEG quality.

``dpi_threshold`` is set notably above ``dpi_target`` (MuPDF guidance) so only
sharper images are resampled. Quality is never “same as source.”

Linearisation (``linear=True``) is **not** offered: current PyMuPDF raises
``Linearisation is no longer supported``.

Fix / normalize page size is Phase 24 — use
``pdf_tools.normalize_pdf_page_size``. Annotation *authoring* / form flatten /
redaction stay in Phases 28–30; sanitize here only optionally strips existing
annotations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import fitz

from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_loader import open_pdf
from pagedrop.core.pdf_tools import STANDARD_METADATA_KEYS

SaveProfileName = Literal["fast", "lossless", "max"]
LossyProfileName = Literal["screen", "ebook", "print"]
CompressProfileName = SaveProfileName | LossyProfileName

# All permission bits MuPDF exposes (matches Document.save default 4095 intent).
_ALL_PERMISSIONS = (
    fitz.PDF_PERM_PRINT
    | fitz.PDF_PERM_MODIFY
    | fitz.PDF_PERM_COPY
    | fitz.PDF_PERM_ANNOTATE
    | fitz.PDF_PERM_FORM
    | fitz.PDF_PERM_ACCESSIBILITY
    | fitz.PDF_PERM_ASSEMBLE
    | fitz.PDF_PERM_PRINT_HQ
)


@dataclass(frozen=True)
class SaveProfile:
    """Named ``Document.save`` argument bundle (see module docstring)."""

    name: SaveProfileName
    garbage: int
    clean: bool
    deflate: bool
    deflate_images: bool
    deflate_fonts: bool
    use_objstms: bool


SAVE_PROFILES: dict[SaveProfileName, SaveProfile] = {
    "fast": SaveProfile(
        name="fast",
        garbage=1,
        clean=False,
        deflate=True,
        deflate_images=False,
        deflate_fonts=False,
        use_objstms=False,
    ),
    "lossless": SaveProfile(
        name="lossless",
        garbage=3,
        clean=True,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        use_objstms=True,
    ),
    "max": SaveProfile(
        name="max",
        garbage=4,
        clean=True,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        use_objstms=True,
    ),
}


@dataclass(frozen=True)
class LossyProfile:
    """Named lossy recompress preset (see module docstring).

    ``dpi`` is the documented target resolution; ``dpi_threshold`` is the MuPDF
    gate (notably above ``dpi``) passed to ``Document.rewrite_images``.
    """

    name: LossyProfileName
    dpi: int
    jpeg_quality: int
    dpi_threshold: int


LOSSY_PROFILES: dict[LossyProfileName, LossyProfile] = {
    "screen": LossyProfile(
        name="screen", dpi=72, jpeg_quality=50, dpi_threshold=100
    ),
    "ebook": LossyProfile(
        name="ebook", dpi=150, jpeg_quality=70, dpi_threshold=200
    ),
    "print": LossyProfile(
        name="print", dpi=300, jpeg_quality=85, dpi_threshold=400
    ),
}


@dataclass(frozen=True)
class RepairResult:
    output_path: str
    was_repaired: bool


@dataclass(frozen=True)
class PdfPermissions:
    """User-facing PDF permission flags (owner can always override)."""

    allow_print: bool = True
    allow_modify: bool = True
    allow_copy: bool = True
    allow_annotate: bool = True
    allow_form: bool = True
    allow_accessibility: bool = True
    allow_assemble: bool = True
    allow_print_hq: bool = True

    def to_fitz(self) -> int:
        bits = 0
        if self.allow_print:
            bits |= fitz.PDF_PERM_PRINT
        if self.allow_modify:
            bits |= fitz.PDF_PERM_MODIFY
        if self.allow_copy:
            bits |= fitz.PDF_PERM_COPY
        if self.allow_annotate:
            bits |= fitz.PDF_PERM_ANNOTATE
        if self.allow_form:
            bits |= fitz.PDF_PERM_FORM
        if self.allow_accessibility:
            bits |= fitz.PDF_PERM_ACCESSIBILITY
        if self.allow_assemble:
            bits |= fitz.PDF_PERM_ASSEMBLE
        if self.allow_print_hq:
            bits |= fitz.PDF_PERM_PRINT_HQ
        return bits


def resolve_save_profile(
    profile: SaveProfileName | SaveProfile = "lossless",
) -> SaveProfile:
    if isinstance(profile, SaveProfile):
        return profile
    try:
        return SAVE_PROFILES[profile]
    except KeyError as exc:
        known = ", ".join(SAVE_PROFILES)
        raise ValueError(f"Unknown save profile {profile!r}; expected one of: {known}") from exc


def resolve_lossy_profile(
    profile: LossyProfileName | LossyProfile,
) -> LossyProfile:
    if isinstance(profile, LossyProfile):
        return profile
    try:
        return LOSSY_PROFILES[profile]
    except KeyError as exc:
        known = ", ".join(LOSSY_PROFILES)
        raise ValueError(
            f"Unknown lossy profile {profile!r}; expected one of: {known}"
        ) from exc


def is_lossy_profile_name(name: str) -> bool:
    return name in LOSSY_PROFILES


def _save_with_profile(doc: fitz.Document, output_path: str, profile: SaveProfile) -> None:
    # lossless mirrors ez_save defaults (including no_new_id / preserve_metadata).
    if profile.name == "lossless":
        doc.ez_save(output_path)
        return
    doc.save(
        output_path,
        garbage=profile.garbage,
        clean=profile.clean,
        deflate=profile.deflate,
        deflate_images=profile.deflate_images,
        deflate_fonts=profile.deflate_fonts,
        use_objstms=profile.use_objstms,
        incremental=False,
    )


def _apply_lossy_images(doc: fitz.Document, profile: LossyProfile) -> None:
    """Downsample + JPEG-recompress image XObjects via MuPDF (in-place on *doc*)."""
    doc.rewrite_images(
        dpi_threshold=profile.dpi_threshold,
        dpi_target=profile.dpi,
        quality=profile.jpeg_quality,
        lossy=True,
        lossless=True,
    )


def compress_pdf(
    source_pdf: str,
    output_path: str,
    *,
    profile: CompressProfileName | SaveProfile | LossyProfile = "lossless",
    password: str | None = None,
) -> None:
    """Rewrite *source_pdf* with a lossless save profile or a lossy image preset.

    Lossy presets (``screen`` / ``ebook`` / ``print``) run ``rewrite_images``
    then a lossless GC save. Quality may drop — never claimed identical.
    """
    reject_source_overwrite(output_path, source_pdf)
    doc = open_pdf(source_pdf, password=password)
    try:
        if isinstance(profile, LossyProfile) or (
            isinstance(profile, str) and is_lossy_profile_name(profile)
        ):
            lossy = resolve_lossy_profile(profile)  # type: ignore[arg-type]
            _apply_lossy_images(doc, lossy)
            _save_with_profile(doc, output_path, SAVE_PROFILES["lossless"])
            return
        resolved = resolve_save_profile(profile)  # type: ignore[arg-type]
        _save_with_profile(doc, output_path, resolved)
    finally:
        doc.close()


def repair_pdf(
    source_pdf: str,
    output_path: str,
    *,
    password: str | None = None,
) -> RepairResult:
    """Open tolerantly, optionally run ``Document.repair``, rewrite to a new path.

    Returns whether MuPDF reported a repair (``is_repaired``) at any point before
    the rewrite. Clean files typically yield ``was_repaired=False``.
    """
    reject_source_overwrite(output_path, source_pdf)
    doc = open_pdf(source_pdf, password=password)
    try:
        was_repaired = bool(getattr(doc, "is_repaired", False))
        repair_fn = getattr(doc, "repair", None)
        if callable(repair_fn):
            repair_fn()
            was_repaired = was_repaired or bool(getattr(doc, "is_repaired", False))
        _save_with_profile(doc, output_path, SAVE_PROFILES["max"])
        return RepairResult(output_path=output_path, was_repaired=was_repaired)
    finally:
        doc.close()


def encrypt_pdf(
    source_pdf: str,
    output_path: str,
    *,
    user_password: str,
    owner_password: str | None = None,
    permissions: PdfPermissions | int | None = None,
    encryption: int = fitz.PDF_ENCRYPT_AES_256,
    password: str | None = None,
) -> None:
    """Write an encrypted copy. Passwords are never persisted by this helper."""
    reject_source_overwrite(output_path, source_pdf)
    if not user_password:
        raise ValueError("user_password must be non-empty")
    owner = owner_password if owner_password is not None else user_password
    if not owner:
        raise ValueError("owner_password must be non-empty")

    if permissions is None:
        perm_bits = _ALL_PERMISSIONS
    elif isinstance(permissions, PdfPermissions):
        perm_bits = permissions.to_fitz()
    else:
        perm_bits = int(permissions)

    if encryption == fitz.PDF_ENCRYPT_NONE:
        raise ValueError("encryption must not be PDF_ENCRYPT_NONE; use decrypt_pdf")

    doc = open_pdf(source_pdf, password=password)
    try:
        doc.save(
            output_path,
            garbage=3,
            deflate=True,
            encryption=encryption,
            permissions=perm_bits,
            user_pw=user_password,
            owner_pw=owner,
            incremental=False,
        )
    finally:
        doc.close()


def decrypt_pdf(
    source_pdf: str,
    output_path: str,
    *,
    password: str,
) -> None:
    """Write an unlocked copy using *password* (user or owner)."""
    reject_source_overwrite(output_path, source_pdf)
    if not password:
        raise ValueError("password must be non-empty")
    doc = open_pdf(source_pdf, password=password)
    try:
        doc.save(
            output_path,
            garbage=3,
            deflate=True,
            encryption=fitz.PDF_ENCRYPT_NONE,
            incremental=False,
        )
    finally:
        doc.close()


def sanitize_pdf(
    source_pdf: str,
    output_path: str,
    *,
    strip_metadata: bool = True,
    strip_xmp: bool = True,
    strip_annotations: bool = False,
    password: str | None = None,
) -> None:
    """Scrub metadata (and optionally annotations) into a new file.

    Annotation strip removes existing markup only — authoring / flatten /
    redaction are Phases 28–30. Coordinates with ``pdf_tools.metadata_strip``
    field set (``STANDARD_METADATA_KEYS`` + optional XMP delete).
    """
    reject_source_overwrite(output_path, source_pdf)
    doc = open_pdf(source_pdf, password=password)
    try:
        if strip_metadata:
            meta = dict(doc.metadata or {})
            for key in STANDARD_METADATA_KEYS:
                if key in meta:
                    meta[key] = ""
            doc.set_metadata(meta)
        if strip_xmp:
            doc.del_xml_metadata()
        if strip_annotations:
            for page in doc:
                for annot in list(page.annots() or []):
                    page.delete_annot(annot)
        _save_with_profile(doc, output_path, SAVE_PROFILES["lossless"])
    finally:
        doc.close()
