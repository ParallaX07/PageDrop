"""Tessdata download: pinned URL, streaming, cancel, hash check; URI scheme allowlist."""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pagedrop.core import tessdata_pack
from pagedrop.core.jobs import CancelToken, JobCancelledError, JobError
from pagedrop.core.tessdata_pack import (
    ENG_FAST_URL,
    TessdataDownloadError,
    download_eng_fast,
    eng_traineddata_path,
)
from pagedrop.utils.safe_url import ALLOWED_OPEN_SCHEMES, is_allowed_open_scheme


class _FakeResponse:
    def __init__(self, payload: bytes, *, on_read=None) -> None:
        self._payload = payload
        self._pos = 0
        self._on_read = on_read
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        if self._on_read is not None:
            self._on_read()
        end = len(self._payload) if size < 0 else self._pos + size
        chunk = self._payload[self._pos : end]
        self._pos += len(chunk)
        return chunk

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

    with pytest.raises(TessdataDownloadError, match="hash mismatch"):
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


def test_download_url_is_pinned_to_a_commit() -> None:
    assert re.search(r"/raw/[0-9a-f]{40}/eng\.traineddata$", ENG_FAST_URL)
    assert "/main/" not in ENG_FAST_URL


def test_download_streams_in_chunks_and_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"x" * (200 * 1024)
    monkeypatch.setattr(tessdata_pack, "ENG_FAST_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse(payload))
    seen: list[float | None] = []

    path = download_eng_fast(dest_dir=tmp_path, on_progress=seen.append)

    assert path.read_bytes() == payload
    assert len(seen) == 4
    assert all(a < b for a, b in zip(seen, seen[1:], strict=False))
    assert seen[-1] == 1.0


def test_download_cancel_mid_stream_keeps_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = eng_traineddata_path(tmp_path)
    target.write_bytes(b"previous-good-data")
    token = CancelToken()
    reads: list[int] = []

    def on_read() -> None:
        reads.append(1)
        if len(reads) == 2:
            token.cancel()

    payload = b"y" * (300 * 1024)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_k: _FakeResponse(payload, on_read=on_read),
    )

    with pytest.raises(JobCancelledError):
        download_eng_fast(dest_dir=tmp_path, cancel=token)

    assert len(reads) == 2
    assert target.read_bytes() == b"previous-good-data"
    assert list(tmp_path.glob("*.partial")) == []


def test_download_network_error_is_typed_and_leaves_no_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(TessdataDownloadError, match="offline") as info:
        download_eng_fast(dest_dir=tmp_path)

    assert isinstance(info.value, JobError)
    assert not eng_traineddata_path(tmp_path).exists()
    assert list(tmp_path.glob("*.partial")) == []
