"""Optional capability registry contracts."""

from __future__ import annotations

import importlib

import pytest

from pagedrop.core import capabilities
from pagedrop.core.capabilities import (
    CAPABILITY_IDS,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
    probe,
    probe_all,
    soft_import,
)


def test_registry_reports_absent_without_crash() -> None:
    clear_cache()
    statuses = probe_all(refresh=True)
    assert set(statuses) == set(CAPABILITY_IDS)
    for cid, status in statuses.items():
        assert status.id == cid
        assert isinstance(status, CapabilityStatus)
        if status.available:
            assert status.reason is None
        else:
            assert status.reason in AbsenceReason
            assert status.detail


def test_optional_import_failure_does_not_break_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashing optional import must soft-fail, not abort probe_all."""

    real_import = importlib.import_module

    def boom(name: str, package: str | None = None):
        if name in {"PIL", "openpyxl", "pi_heif", "cv2", "win32com.client"}:
            raise RuntimeError(f"simulated broken optional: {name}")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", boom)
    clear_cache()
    statuses = probe_all(refresh=True)
    assert set(statuses) == set(CAPABILITY_IDS)
    # Python packs that go through soft_import must report typed absence.
    for cid in (
        capabilities.PILLOW,
        capabilities.OPENPYXL,
        capabilities.PI_HEIF,
        capabilities.OPENCV,
    ):
        assert statuses[cid].available is False
        assert statuses[cid].reason in {
            AbsenceReason.CODEC_MISSING,
            AbsenceReason.ENGINE_MISSING,
        }


def test_soft_import_swallows_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional packages that call sys.exit on import must not kill the app."""
    real = importlib.import_module

    def boom(name: str, package: str | None = None):
        if name == "_pagedrop_fake_exiting_optional":
            raise SystemExit(42)
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", boom)
    mod_out, err = soft_import("_pagedrop_fake_exiting_optional")
    assert mod_out is None
    assert isinstance(err, SystemExit)


def test_typed_absence_reasons_are_stable() -> None:
    assert {r.value for r in AbsenceReason} == {
        "engine_missing",
        "data_missing",
        "codec_missing",
        "licence_blocked",
    }


def test_probe_unknown_id_raises() -> None:
    with pytest.raises(KeyError, match="unknown capability"):
        probe("not_a_real_capability")


def test_codec_vs_engine_reason_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_missing(module_name: str) -> tuple[None, Exception]:
        return None, ImportError(module_name)

    monkeypatch.setattr(capabilities, "soft_import", always_missing)
    clear_cache()
    statuses = probe_all(refresh=True)
    assert statuses[capabilities.PILLOW].reason == AbsenceReason.CODEC_MISSING
    assert statuses[capabilities.OPENPYXL].reason == AbsenceReason.CODEC_MISSING
    assert statuses[capabilities.PI_HEIF].reason == AbsenceReason.CODEC_MISSING
    assert statuses[capabilities.OPENCV].reason == AbsenceReason.ENGINE_MISSING


def test_tessdata_reports_languages(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "tessdata"
    data.mkdir()
    (data / "eng.traineddata").write_bytes(b"x")
    (data / "deu.traineddata").write_bytes(b"x")
    (data / "osd.traineddata").write_bytes(b"x")  # ignored meta
    monkeypatch.setenv("PAGEDROP_TESSDATA", str(data))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    clear_cache()
    status = probe(capabilities.TESSDATA, refresh=True)
    assert status.available is True
    assert status.extras["languages"] == ["deu", "eng"]
    assert status.extras["path"] == str(data.resolve())


def test_libreoffice_env_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "soffice"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PAGEDROP_LO_PATH", str(fake))
    monkeypatch.setattr(capabilities.shutil, "which", lambda _name: None)
    clear_cache()
    status = probe(capabilities.LIBREOFFICE, refresh=True)
    assert status.available is True
    assert status.extras["path"] == str(fake.resolve())
