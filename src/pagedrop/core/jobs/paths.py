"""Path guards for jobs — samefile / resolve rules matching Save As."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.jobs.errors import OutputExistsError, SourceOverwriteError


def paths_refer_to_same_file(left: str | Path, right: str | Path) -> bool:
    """True when *left* and *right* name the same filesystem object."""
    try:
        return Path(left).resolve().samefile(Path(right).resolve())
    except OSError:
        return Path(left).resolve() == Path(right).resolve()


def reject_source_overwrite(
    output: str | Path,
    *sources: str | Path,
) -> None:
    """Raise ``SourceOverwriteError`` if *output* resolves to any source path."""
    for source in sources:
        if paths_refer_to_same_file(output, source):
            raise SourceOverwriteError(str(Path(output)))


def ensure_output_destination(
    output: str | Path,
    *,
    sources: tuple[str | Path, ...] = (),
    overwrite: bool = False,
) -> Path:
    """Validate *output* against sources and existing files; return resolved Path."""
    out = Path(output)
    if sources:
        reject_source_overwrite(out, *sources)
    if out.exists() and not overwrite:
        raise OutputExistsError(str(out))
    return out
