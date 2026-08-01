"""WC3 — tessdata download hash pin + URI scheme allowlist helper."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

import pytest

from pagedrop.core import tessdata_pack
from pagedrop.core.tessdata_pack import download_eng_fast, eng_traineddata_path
from pagedrop.utils.safe_url import ALLOWED_OPEN_SCHEMES, is_allowed_open_scheme


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def test_allowed_open_schemes() -> None:
    assert ALLOWED_OPEN_SCHEMES == frozenset({"http", "https", "mailto"})
    assert is_allowed_open_scheme("https")
    assert is_allowed_open_scheme("HTTP")
    assert is_allowed_open_scheme("mailto")
    assert not is_allowed_open_scheme("file")
    assert not is_allowed_open_scheme("javascript")
    assert not is_allowed_open_scheme("")


def test_download_eng_fast_hash_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "tessdata"
    dest.mkdir()
    payload = b"not-a-real-traineddata-file"

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_k: _FakeResponse(payload),
    )

    with pytest.raises(RuntimeError, match="hash mismatch"):
        download_eng_fast(dest_dir=dest)

    assert not eng_traineddata_path(dest).exists()
    assert list(dest.glob("*.partial")) == []


def test_download_eng_fast_accepts_matching_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "tessdata"
    dest.mkdir()
    payload = b"fake-eng-traineddata-ok"
    expected = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(tessdata_pack, "ENG_FAST_SHA256", expected)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_k: _FakeResponse(payload),
    )

    path = download_eng_fast(dest_dir=dest)
    assert path == eng_traineddata_path(dest)
    assert path.read_bytes() == payload
    assert list(dest.glob("*.partial")) == []
