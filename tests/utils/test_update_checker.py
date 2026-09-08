"""Release checker regressions use local fake HTTP responses only."""

from __future__ import annotations

import hashlib
import io
import json
import threading
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

import pagedrop.utils.update_checker as update_checker
from pagedrop.utils.update_checker import (
    REPOSITORY,
    RateLimitedError,
    ReleaseDataError,
    ReleaseInfo,
    ReleaseNotFoundError,
    UnsafeUpdateUrlError,
    UpdateCancelledError,
    UpdateDownloadError,
    UpdateNetworkError,
    check_for_update,
    download_installer,
    fetch_latest_release,
    is_newer,
)

MANIFEST_URL = update_checker.MANIFEST_URL


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, *, code: int = 200, headers: dict[str, str] | None = None, url: str = ""):
        super().__init__(body)
        self._code = code
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self._url = url

    def getcode(self):
        return self._code

    def geturl(self):
        return self._url


class FakeOpen:
    def __init__(self, responses: dict[str, FakeResponse | Exception]):
        self.responses = responses
        self.requests: list[str] = []

    def __call__(self, request, timeout):
        self.requests.append(request.full_url)
        response = self.responses[request.full_url]
        if isinstance(response, Exception):
            raise response
        return response


class InterruptingResponse(FakeResponse):
    def __init__(self, first_chunk: bytes, event: threading.Event | None = None):
        super().__init__(first_chunk)
        self._event = event
        self._reads = 0

    def read(self, size: int = -1) -> bytes:
        self._reads += 1
        if self._reads == 1:
            chunk = super().read(size)
            if self._event:
                self._event.set()
            return chunk
        if self._reads == 2:
            raise OSError("connection interrupted")
        return b""


def _asset_url(tag: str, name: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"


def _manifest(**changes):
    data = {"schema_version": 1, "version": "1.10.0", "installer_size": 4,
            "installer_sha256": "a" * 64, "notes": "Notes"}
    data.update(changes)
    return json.dumps(data).encode()


def test_numeric_versions_and_single_manifest_request():
    assert is_newer("1.10.0", "1.9.0")
    opener = FakeOpen({MANIFEST_URL: FakeResponse(_manifest(extra=True, installer_url="https://evil.test"))})
    release = check_for_update("1.9.0", open_url=opener)
    assert release.installer_url == _asset_url("v1.10.0", "PageDrop-1.10.0-Setup.exe")
    assert opener.requests == [MANIFEST_URL]
    assert check_for_update("1.10.0", open_url=FakeOpen({MANIFEST_URL: FakeResponse(_manifest())})) is None
    with pytest.raises(ReleaseDataError):
        check_for_update("0.0.0-dev", open_url=opener)


@pytest.mark.parametrize("field,value", [
    ("schema_version", None), ("schema_version", True), ("schema_version", 2),
    ("schema_version", 1.0), ("version", "1.2"), ("version", "01.2.3"),
    ("version", "1.2.3-beta"), ("version", None), ("installer_size", True),
    ("installer_size", 0), ("installer_size", -1), ("installer_size", "4"),
    ("installer_sha256", "A" * 64), ("installer_sha256", "a" * 63),
    ("installer_sha256", None), ("notes", None), ("notes", 4),
])
def test_invalid_manifest_fields(field, value):
    with pytest.raises(ReleaseDataError):
        fetch_latest_release(open_url=FakeOpen({MANIFEST_URL: FakeResponse(_manifest(**{field: value}))}))


@pytest.mark.parametrize("body", [b"{}", b"[]", b"not json", b"\xff", b"x" * (1024 * 1024 + 1)],
                         ids=["empty", "array", "invalid-json", "invalid-utf8", "oversized"])
def test_invalid_manifest_body(body):
    with pytest.raises(ReleaseDataError):
        fetch_latest_release(open_url=FakeOpen({MANIFEST_URL: FakeResponse(body)}))


def test_metadata_redirects_and_missing_manifest():
    final = "https://release-assets.githubusercontent.com/file"
    opener = FakeOpen({MANIFEST_URL: FakeResponse(b"", code=302, headers={"Location": final}),
                       final: FakeResponse(_manifest())})
    assert fetch_latest_release(open_url=opener).version == "1.10.0"
    with pytest.raises(ReleaseNotFoundError):
        fetch_latest_release(open_url=FakeOpen({
            MANIFEST_URL: FakeResponse(b"", code=302, headers={"Location": final}),
            final: HTTPError(final, 404, "missing", Message(), None)}))
    with pytest.raises(UnsafeUpdateUrlError):
        fetch_latest_release(open_url=FakeOpen({
            MANIFEST_URL: FakeResponse(b"", code=302, headers={"Location": "https://evil.test"})}))


def test_metadata_timeout_and_rate_limit():
    with pytest.raises(update_checker.UpdateTimeoutError):
        fetch_latest_release(open_url=FakeOpen({MANIFEST_URL: TimeoutError("slow")}))
    with pytest.raises(RateLimitedError) as exc:
        fetch_latest_release(open_url=FakeOpen({
            MANIFEST_URL: FakeResponse(b"", code=429, headers={"Retry-After": "60"})}))
    assert exc.value.retry_after is not None
    assert update_checker._retry_after({"Retry-After": "garbage", "X-RateLimit-Reset": "9" * 100}) is None
    assert update_checker._retry_after({"Retry-After": "Wed, 09 Sep 2026 12:00:00 GMT"}) is not None


@pytest.mark.parametrize("status", [403, 503])
def test_service_retry_after_is_honored_without_api_quota_headers(status):
    with pytest.raises(RateLimitedError) as exc:
        fetch_latest_release(open_url=FakeOpen({
            MANIFEST_URL: FakeResponse(b"", code=status, headers={"Retry-After": "120"})}))
    assert exc.value.retry_after is not None


def test_download_redirects_only_to_exact_allowed_hosts(tmp_path: Path):
    payload = b"good"
    release = _ready_release(payload)
    final_url = "https://release-assets.githubusercontent.com/download?token=private"
    opener = FakeOpen({
        release.installer_url: FakeResponse(b"", code=302, headers={"Location": final_url}),
        final_url: FakeResponse(payload),
    })
    assert download_installer(release, tmp_path / release.installer_name, open_url=opener).read_bytes() == payload
    (tmp_path / release.installer_name).unlink()
    bad = FakeOpen({release.installer_url: FakeResponse(b"", code=302, headers={"Location": "https://evil.test/file"})})
    with pytest.raises(UnsafeUpdateUrlError):
        download_installer(release, tmp_path / "PageDrop-2.0.0-Setup.exe", open_url=bad)


def test_download_promotes_only_exact_size_and_digest_and_reports_progress(tmp_path: Path):
    payload = b"exact bytes"
    release = _ready_release(payload)
    opener = FakeOpen({release.installer_url: FakeResponse(payload)})
    progress: list[tuple[int, int]] = []
    destination = tmp_path / release.installer_name
    assert download_installer(
        release, destination, open_url=opener, progress=lambda current, total: progress.append((current, total))
    ) == destination
    assert progress == [(0, len(payload)), (len(payload), len(payload))]
    assert destination.read_bytes() == payload
    destination.unlink()
    wrong_size = _ready_release(payload, size=len(payload) - 1)
    with pytest.raises(UpdateDownloadError):
        download_installer(wrong_size, tmp_path / wrong_size.installer_name, open_url=FakeOpen({wrong_size.installer_url: FakeResponse(payload)}))
    assert not (tmp_path / f"{wrong_size.installer_name}.part").exists()


def test_download_cancellation_and_read_failure_remove_partial_file(tmp_path: Path):
    payload = b"exact bytes"
    release = _ready_release(payload)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(UpdateCancelledError):
        download_installer(release, tmp_path / release.installer_name, cancel_event=cancelled)
    assert not (tmp_path / f"{release.installer_name}.part").exists()
    with pytest.raises(UpdateNetworkError):
        download_installer(release, tmp_path / release.installer_name, open_url=FakeOpen({release.installer_url: OSError("read failed")}))
    assert not (tmp_path / f"{release.installer_name}.part").exists()


def test_download_truncation_interruption_and_midstream_cancel_clean_up(tmp_path: Path):
    payload = b"exact bytes"
    release = _ready_release(payload)
    with pytest.raises(UpdateDownloadError, match="verified"):
        download_installer(release, tmp_path / release.installer_name, open_url=FakeOpen({release.installer_url: FakeResponse(payload[:-1])}))
    assert not (tmp_path / f"{release.installer_name}.part").exists()
    with pytest.raises(UpdateNetworkError):
        download_installer(release, tmp_path / release.installer_name, open_url=FakeOpen({release.installer_url: InterruptingResponse(payload[:2])}))
    assert not (tmp_path / f"{release.installer_name}.part").exists()
    cancelled = threading.Event()
    with pytest.raises(UpdateCancelledError):
        download_installer(release, tmp_path / release.installer_name, cancel_event=cancelled, open_url=FakeOpen({release.installer_url: InterruptingResponse(payload[:2], cancelled)}))
    assert not (tmp_path / f"{release.installer_name}.part").exists()


def test_disk_error_removes_the_owned_partial_file(tmp_path: Path, monkeypatch):
    release = _ready_release(b"bytes")

    def fail_after_write(release, output, *args):
        output.write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(update_checker, "_download_to", fail_after_write)
    with pytest.raises(UpdateDownloadError, match="save"):
        download_installer(release, tmp_path / release.installer_name)
    assert not (tmp_path / f"{release.installer_name}.part").exists()


def test_unexpected_download_failure_cleans_partial_and_closes_response(tmp_path):
    release = _ready_release(b"bytes")
    response = FakeResponse(b"bytes")
    def progress(done, total):
        if done:
            raise RuntimeError("unexpected")
    with pytest.raises(RuntimeError):
        download_installer(release, tmp_path / release.installer_name,
                           open_url=FakeOpen({release.installer_url: response}), progress=progress)
    assert response.closed
    assert not (tmp_path / f"{release.installer_name}.part").exists()


def _ready_release(payload: bytes, *, size: int | None = None) -> ReleaseInfo:
    version = "2.0.0"
    name = f"PageDrop-{version}-Setup.exe"
    tag = f"v{version}"
    return ReleaseInfo(version, tag, name, _asset_url(tag, name), size if size is not None else len(payload), "", hashlib.sha256(payload).hexdigest())
