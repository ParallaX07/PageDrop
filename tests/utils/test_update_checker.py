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

API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"


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


def _metadata(*, version: str = "1.10.0", assets: list[dict[str, object]] | None = None) -> tuple[bytes, str, str, str]:
    tag = f"v{version}"
    installer = f"PageDrop-{version}-Setup.exe"
    checksum = f"{installer}.sha256"
    if assets is None:
        assets = [
            {"name": installer, "browser_download_url": _asset_url(tag, installer), "size": 4, "state": "uploaded"},
            {"name": checksum, "browser_download_url": _asset_url(tag, checksum), "size": 80, "state": "uploaded"},
        ]
    return json.dumps({"tag_name": tag, "draft": False, "prerelease": False, "body": "Notes", "assets": assets}).encode(), tag, installer, checksum


def _release_info(data: bytes, tag: str, installer: str, checksum: str, *, checksum_data: bytes | None = None):
    checksum_data = checksum_data or f"{'a' * 64}  {installer}\n".encode()
    return FakeOpen({API_URL: FakeResponse(data), _asset_url(tag, checksum): FakeResponse(checksum_data)})


def test_numeric_versions_and_installed_validation():
    assert is_newer("1.10.0", "1.9.0")
    data, tag, installer, checksum = _metadata()
    opener = _release_info(data, tag, installer, checksum)
    assert check_for_update("1.10.0", open_url=opener) is None
    with pytest.raises(ReleaseDataError, match="application version"):
        check_for_update("0.0.0-dev", open_url=opener)


@pytest.mark.parametrize("field", ["draft", "prerelease"])
def test_drafts_and_prereleases_are_rejected(field):
    data, tag, installer, checksum = _metadata()
    payload = json.loads(data)
    payload[field] = True
    with pytest.raises(ReleaseDataError, match="stable"):
        fetch_latest_release(open_url=_release_info(json.dumps(payload).encode(), tag, installer, checksum))


def test_metadata_404_and_rate_limit_are_distinct():
    not_found = FakeOpen({API_URL: HTTPError(API_URL, 404, "missing", Message(), None)})
    with pytest.raises(ReleaseNotFoundError):
        fetch_latest_release(open_url=not_found)
    headers = Message()
    headers["X-RateLimit-Remaining"] = "0"
    headers["X-RateLimit-Reset"] = "2000000000"
    limited = FakeOpen({API_URL: HTTPError(API_URL, 403, "limited", headers, None)})
    with pytest.raises(RateLimitedError) as exc:
        fetch_latest_release(open_url=limited)
    assert exc.value.retry_after is not None


def test_metadata_timeout_and_oversized_response_are_rejected():
    with pytest.raises(UpdateNetworkError, match="contact"):
        fetch_latest_release(open_url=FakeOpen({API_URL: TimeoutError("slow")}))
    with pytest.raises(ReleaseDataError, match="too large"):
        fetch_latest_release(open_url=FakeOpen({API_URL: FakeResponse(b"x" * (1024 * 1024 + 1))}))


def test_bad_assets_urls_and_checksum_are_rejected():
    data, tag, installer, checksum = _metadata()
    payload = json.loads(data)
    payload["assets"][0]["browser_download_url"] = "https://github.com.evil.test/file.exe"
    with pytest.raises(UnsafeUpdateUrlError):
        fetch_latest_release(open_url=_release_info(json.dumps(payload).encode(), tag, installer, checksum))
    with pytest.raises(ReleaseDataError, match="checksum"):
        fetch_latest_release(open_url=_release_info(data, tag, installer, checksum, checksum_data=b"not-a-checksum\n"))
    with pytest.raises(ReleaseDataError, match="checksum"):
        fetch_latest_release(open_url=_release_info(data, tag, installer, checksum, checksum_data=f"{'a' * 64}  other.exe\n".encode()))


def test_duplicate_assets_and_missing_uploaded_state_are_rejected():
    data, tag, installer, checksum = _metadata()
    payload = json.loads(data)
    payload["assets"].append(dict(payload["assets"][0]))
    with pytest.raises(ReleaseDataError, match="duplicate"):
        fetch_latest_release(open_url=_release_info(json.dumps(payload).encode(), tag, installer, checksum))


def test_missing_assets_and_unsafe_initial_checksum_url_are_rejected():
    data, tag, installer, checksum = _metadata()
    payload = json.loads(data)
    payload["assets"].pop()
    with pytest.raises(ReleaseDataError, match="missing"):
        fetch_latest_release(open_url=_release_info(json.dumps(payload).encode(), tag, installer, checksum))
    payload = json.loads(data)
    payload["assets"][1]["browser_download_url"] = "http://github.com/not-safe"
    with pytest.raises(UnsafeUpdateUrlError):
        fetch_latest_release(open_url=_release_info(json.dumps(payload).encode(), tag, installer, checksum))
    payload = json.loads(data)
    payload["draft"] = "false"
    with pytest.raises(ReleaseDataError, match="stable"):
        fetch_latest_release(open_url=_release_info(json.dumps(payload).encode(), tag, installer, checksum))
    payload = json.loads(data)
    payload["assets"][0]["state"] = "new"
    with pytest.raises(ReleaseDataError, match="uploaded"):
        fetch_latest_release(open_url=_release_info(json.dumps(payload).encode(), tag, installer, checksum))


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
    with pytest.raises(UpdateDownloadError):
        download_installer(release, tmp_path / release.installer_name, open_url=FakeOpen({release.installer_url: OSError("read failed")}))
    assert not (tmp_path / f"{release.installer_name}.part").exists()


def test_download_truncation_interruption_and_midstream_cancel_clean_up(tmp_path: Path):
    payload = b"exact bytes"
    release = _ready_release(payload)
    with pytest.raises(UpdateDownloadError, match="verified"):
        download_installer(release, tmp_path / release.installer_name, open_url=FakeOpen({release.installer_url: FakeResponse(payload[:-1])}))
    assert not (tmp_path / f"{release.installer_name}.part").exists()
    with pytest.raises(UpdateDownloadError):
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


def _ready_release(payload: bytes, *, size: int | None = None) -> ReleaseInfo:
    version = "2.0.0"
    name = f"PageDrop-{version}-Setup.exe"
    tag = f"v{version}"
    return ReleaseInfo(version, tag, name, _asset_url(tag, name), _asset_url(tag, f"{name}.sha256"), size if size is not None else len(payload), "", hashlib.sha256(payload).hexdigest())
