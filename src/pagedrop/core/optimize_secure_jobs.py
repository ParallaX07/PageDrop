"""Job handlers for Optimize & Secure tools (Phase 27)."""

from __future__ import annotations

from pathlib import Path

import fitz

from pagedrop.core import optimize_secure as ops
from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner


def _password(ctx: JobContext) -> str | None:
    return ctx.credentials.get(ctx.spec.inputs[0])


def handle_compress(ctx: JobContext) -> Path:
    profile_name = str(ctx.spec.options.get("profile") or "lossless")
    if ops.is_lossy_profile_name(profile_name):
        lossy = ops.resolve_lossy_profile(profile_name)  # type: ignore[arg-type]
        # Optional overrides from job options (UI / advanced callers).
        dpi = int(ctx.spec.options.get("dpi") or lossy.dpi)
        jpeg_quality = int(ctx.spec.options.get("jpeg_quality") or lossy.jpeg_quality)
        dpi_threshold = int(ctx.spec.options.get("dpi_threshold") or lossy.dpi_threshold)
        if dpi_threshold <= dpi:
            dpi_threshold = dpi + 1
        profile: ops.LossyProfile | str = ops.LossyProfile(
            name=lossy.name,
            dpi=dpi,
            jpeg_quality=jpeg_quality,
            dpi_threshold=dpi_threshold,
        )
        ctx.progress(
            0.3,
            f"Compressing PDF (lossy {lossy.name}, {dpi} DPI, Q{jpeg_quality})…",
        )
    else:
        # Validate early so unknown names fail before opening the PDF.
        if profile_name not in ops.SAVE_PROFILES:
            known = ", ".join([*ops.SAVE_PROFILES, *ops.LOSSY_PROFILES])
            raise ValueError(
                f"Unknown compress profile {profile_name!r}; expected one of: {known}"
            )
        profile = profile_name
        ctx.progress(0.3, "Compressing PDF…")

    ops.compress_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        profile=profile,
        password=_password(ctx),
    )
    return ctx.staged_output


def handle_repair(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Repairing PDF…")
    result = ops.repair_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        password=_password(ctx),
    )
    if result.was_repaired:
        ctx.progress(0.8, "Repair applied; rewriting…")
    else:
        ctx.progress(0.8, "Rewriting clean copy…")
    return ctx.staged_output


def handle_encrypt(ctx: JobContext) -> Path:
    user_pw = ctx.secrets.get("user_password") or ""
    owner_pw = ctx.secrets.get("owner_password")
    if owner_pw is None or owner_pw == "":
        owner_pw = user_pw

    perm_opts = ctx.spec.options.get("permissions") or {}
    permissions = ops.PdfPermissions(
        allow_print=bool(perm_opts.get("allow_print", True)),
        allow_modify=bool(perm_opts.get("allow_modify", True)),
        allow_copy=bool(perm_opts.get("allow_copy", True)),
        allow_annotate=bool(perm_opts.get("allow_annotate", True)),
        allow_form=bool(perm_opts.get("allow_form", True)),
        allow_accessibility=bool(perm_opts.get("allow_accessibility", True)),
        allow_assemble=bool(perm_opts.get("allow_assemble", True)),
        allow_print_hq=bool(perm_opts.get("allow_print_hq", True)),
    )

    enc_name = str(ctx.spec.options.get("encryption") or "AES-256")
    encryption = {
        "AES-256": fitz.PDF_ENCRYPT_AES_256,
        "AES-128": fitz.PDF_ENCRYPT_AES_128,
    }.get(enc_name, fitz.PDF_ENCRYPT_AES_256)

    ctx.progress(0.3, "Encrypting PDF…")
    ops.encrypt_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        user_password=user_pw,
        owner_password=owner_pw,
        permissions=permissions,
        encryption=encryption,
        password=_password(ctx),
    )
    return ctx.staged_output


def handle_decrypt(ctx: JobContext) -> Path:
    password = _password(ctx)
    if not password:
        raise ValueError("Password required to decrypt this PDF")
    ctx.progress(0.3, "Decrypting PDF…")
    ops.decrypt_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        password=password,
    )
    return ctx.staged_output


def handle_sanitize(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Sanitizing PDF…")
    ops.sanitize_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        strip_metadata=bool(ctx.spec.options.get("strip_metadata", True)),
        strip_xmp=bool(ctx.spec.options.get("strip_xmp", True)),
        strip_annotations=bool(ctx.spec.options.get("strip_annotations", False)),
        password=_password(ctx),
        cancel=ctx.cancel,
    )
    return ctx.staged_output


OPTIMIZE_SECURE_HANDLERS: dict[str, object] = {
    "compress": handle_compress,
    "repair": handle_repair,
    "encrypt": handle_encrypt,
    "decrypt": handle_decrypt,
    "sanitize": handle_sanitize,
}


def register_optimize_secure_handlers(runner: SerializedJobRunner) -> None:
    for job_type, handler in OPTIMIZE_SECURE_HANDLERS.items():
        runner.register(job_type, handler)  # type: ignore[arg-type]
