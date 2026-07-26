"""Job specification and progress reporting (no credentials, no Qt)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ProgressCallback = Callable[[float, str], None]
"""``(fraction_0_to_1, status_message)`` — status for running work ends with ``…``."""


def _noop_progress(_fraction: float, _message: str) -> None:
    return None


@dataclass(frozen=True)
class JobSpec:
    """Persistable job request. Never store passwords or cert secrets here."""

    job_type: str
    inputs: tuple[str, ...]
    output: str
    options: Mapping[str, Any] = field(default_factory=dict)
    overwrite: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "inputs",
            tuple(str(Path(p)) for p in self.inputs),
        )
        object.__setattr__(self, "output", str(Path(self.output)))
        # Freeze options as a plain dict copy so callers cannot mutate later.
        object.__setattr__(self, "options", dict(self.options))

    @classmethod
    def create(
        cls,
        job_type: str,
        *,
        inputs: Sequence[str | Path],
        output: str | Path,
        options: Mapping[str, Any] | None = None,
        overwrite: bool = False,
    ) -> JobSpec:
        return cls(
            job_type=job_type,
            inputs=tuple(str(p) for p in inputs),
            output=str(output),
            options=dict(options or {}),
            overwrite=overwrite,
        )

    def to_persistable_dict(self) -> dict[str, Any]:
        """JSON-friendly snapshot safe for logs / workflow files (no secrets)."""
        return {
            "job_type": self.job_type,
            "inputs": list(self.inputs),
            "output": self.output,
            "options": dict(self.options),
            "overwrite": self.overwrite,
        }
