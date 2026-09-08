"""Fetch and verify PageDrop Windows release installers without Qt."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "ParallaX07/PageDrop"
_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_USER_AGENT = "PageDrop-updater"
_METADATA_LIMIT = 1024 * 1024
_CHECKSUM_LIMIT = 4096
_SOCKET_TIMEOUT = 10.0
_DOWNLOAD_SOCKET_TIMEOUT = 15.0
_METADATA_DEADLINE = 30.0
_DOWNLOAD_DEADLINE = 30 * 60.0
_MAX_REDIRECTS = 5
_CHUNK_SIZE = 64 * 1024
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_HOSTS = frozenset(
    {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)


class UpdateCheckError(RuntimeError):
    """Base class for sanitized updater failures."""


class ReleaseNotFoundError(UpdateCheckError):
    """The public repository has no published stable release."""


class ReleaseDataError(UpdateCheckError):
    """GitHub returned a release that does not meet PageDrop's contract."""


class UnsafeUpdateUrlError(ReleaseDataError):
    """A release asset or redirect target is not a trusted HTTPS URL."""


class UpdateNetworkError(UpdateCheckError):
    """The updater could not reach the release service."""


class UpdateTimeoutError(UpdateNetworkError):
    """A bounded updater operation exceeded its deadline."""


class RateLimitedError(UpdateNetworkError):
    """GitHub refused a request because its rate limit was reached."""

    def __init__(self, retry_after: datetime | None) -> None:
        self.retry_after = retry_after
        super().__init__("Update checks are temporarily rate limited")


class UpdateDownloadError(UpdateCheckError):
    """Installer bytes could not be safely downloaded or verified."""


class UpdateCancelledError(UpdateDownloadError):
    """The caller cancelled the download."""


@dataclass(frozen=True)
class ReleaseInfo:
    """A stable release whose exact installer and digest are known."""

    version: str
    tag: str
    installer_name: str
    installer_url: str
    checksum_url: str
    installer_size: int
    notes: str
    expected_sha256: str

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        return parse_version(self.version)


class _Response(Protocol):
    headers: object

    def read(self, size: int = -1) -> bytes: ...

    def getcode(self) -> int | None: ...

    def geturl(self) -> str: ...

    def close(self) -> None: ...


OpenUrl = Callable[[Request, float], _Response]
ProgressCallback = Callable[[int, int], None]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def parse_version(value: str) -> tuple[int, int, int]:
    """Return a strict numeric ``MAJOR.MINOR.PATCH`` version tuple."""
    if not isinstance(value, str) or not (match := _VERSION_RE.fullmatch(value)):
        raise ReleaseDataError("Invalid application version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer(release_version: str, installed_version: str) -> bool:
    """Compare strict numeric versions without lexicographic ordering."""
    return parse_version(release_version) > parse_version(installed_version)


def fetch_latest_release(*, open_url: OpenUrl | None = None, monotonic: Callable[[], float] = time.monotonic, cancel_event: threading.Event | None = None) -> ReleaseInfo:
    """Fetch and validate the latest public stable release metadata."""
    opener = open_url or _stdlib_open
    started = monotonic()
    response = _request(
        _API_URL, opener, _SOCKET_TIMEOUT, monotonic, started, _METADATA_DEADLINE, False, cancel_event
    )
    try:
        raw = _read_limited(response, _METADATA_LIMIT, monotonic, started, _METADATA_DEADLINE, cancel_event)
    finally:
        response.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseDataError("Release metadata is not valid JSON") from exc
    return _release_from_data(data, opener, monotonic, started, cancel_event)


def check_for_update(installed_version: str, **kwargs: object) -> ReleaseInfo | None:
    """Return a newer release, while rejecting an invalid installed version."""
    parse_version(installed_version)
    release = fetch_latest_release(**kwargs)  # type: ignore[arg-type]
    return release if is_newer(release.version, installed_version) else None


def download_installer(
    release: ReleaseInfo,
    destination: Path,
    *,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    open_url: OpenUrl | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> Path:
    """Stream, hash, and atomically promote a verified installer to *destination*.

    A blocking socket read can take up to the configured 15-second socket timeout
    to observe cancellation.
    """
    if destination.name != release.installer_name:
        raise UpdateDownloadError("Installer destination does not match the release")
    if destination.exists():
        raise UpdateDownloadError("Installer destination already exists")
    part = destination.with_name(f"{destination.name}.part")
    try:
        with part.open("xb") as output:
            _download_to(
                release, output, cancel_event, progress, open_url or _stdlib_open, monotonic
            )
        os.replace(part, destination)
        return destination
    except UpdateCheckError:
        _remove_owned(part)
        raise
    except OSError as exc:
        _remove_owned(part)
        raise UpdateDownloadError("Could not save the update installer") from exc


def _release_from_data(data: object, opener: OpenUrl, monotonic: Callable[[], float], started: float, cancel_event: threading.Event | None = None) -> ReleaseInfo:
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("draft"), bool)
        or not isinstance(data.get("prerelease"), bool)
        or data["draft"]
        or data["prerelease"]
    ):
        raise ReleaseDataError("Latest release is not a stable published release")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ReleaseDataError("Release tag is invalid")
    version = tag.removeprefix("v")
    parse_version(version)
    assets = data.get("assets")
    notes = data.get("body")
    if not isinstance(assets, list) or not isinstance(notes, str):
        raise ReleaseDataError("Release metadata has invalid fields")
    installer_name = f"PageDrop-{version}-Setup.exe"
    checksum_name = f"{installer_name}.sha256"
    matching: dict[str, dict[str, object]] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise ReleaseDataError("Release asset is malformed")
        name = asset["name"]
        if name in matching:
            raise ReleaseDataError("Release contains duplicate asset names")
        matching[name] = asset
    try:
        installer, checksum = matching[installer_name], matching[checksum_name]
    except KeyError as exc:
        raise ReleaseDataError("Release is missing its installer or checksum") from exc
    installer_url = _asset_url(installer, tag, installer_name)
    checksum_url = _asset_url(checksum, tag, checksum_name)
    size = installer.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ReleaseDataError("Installer size is invalid")
    if (
        not isinstance(checksum.get("size"), int)
        or isinstance(checksum["size"], bool)
        or checksum["size"] <= 0
    ):
        raise ReleaseDataError("Checksum size is invalid")
    checksum_response = _request(
        checksum_url, opener, _SOCKET_TIMEOUT, monotonic, started, _METADATA_DEADLINE, True, cancel_event
    )
    try:
        checksum_bytes = _read_limited(checksum_response, _CHECKSUM_LIMIT, monotonic, started, _METADATA_DEADLINE, cancel_event)
    finally:
        checksum_response.close()
    digest = _parse_checksum(checksum_bytes, installer_name)
    return ReleaseInfo(version, tag, installer_name, installer_url, checksum_url, size, notes, digest)


def _asset_url(asset: dict[str, object], tag: str, name: str) -> str:
    if asset.get("state") != "uploaded":
        raise ReleaseDataError("Release asset is not uploaded")
    url = asset.get("browser_download_url")
    if not isinstance(url, str):
        raise ReleaseDataError("Release asset URL is invalid")
    _validate_initial_asset_url(url, tag, name)
    return url


def _validate_initial_asset_url(url: str, tag: str, name: str) -> None:
    parsed = _split_update_url(url)
    expected = f"/{REPOSITORY}/releases/download/{tag}/{name}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != expected
        or parsed.query
        or parsed.fragment
    ):
        raise UnsafeUpdateUrlError("Release asset URL is not trusted")


def _validate_redirect_url(url: str) -> None:
    parsed = _split_update_url(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _RELEASE_HOSTS
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise UnsafeUpdateUrlError("Release download redirect is not trusted")


def _split_update_url(url: str):  # type: ignore[no-untyped-def]
    try:
        parsed = urlsplit(url)
        _ = parsed.port
        return parsed
    except ValueError as exc:
        raise UnsafeUpdateUrlError("Release URL is invalid") from exc


def _request(
    url: str,
    opener: OpenUrl,
    socket_timeout: float,
    monotonic: Callable[[], float],
    started: float,
    deadline: float,
    allow_redirects: bool,
    cancel_event: threading.Event | None = None,
) -> _Response:
    current = url
    for redirect_count in range(_MAX_REDIRECTS + 1):
        _ensure_not_cancelled(cancel_event)
        _ensure_before_deadline(monotonic, started, deadline)
        request = Request(current, headers={"User-Agent": _USER_AGENT, "Accept": "application/octet-stream"})
        try:
            response = opener(request, socket_timeout)
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                response = exc
            else:
                if exc.code == 404 and current == _API_URL:
                    raise ReleaseNotFoundError("No published PageDrop release is available") from exc
                _raise_http_error(exc)
        except (TimeoutError, URLError, OSError) as exc:
            raise UpdateNetworkError("Could not contact the update service") from exc
        code = response.getcode() or 200
        if 300 <= code < 400:
            location = _header(response.headers, "Location")
            response.close()
            if not allow_redirects or not isinstance(location, str) or redirect_count == _MAX_REDIRECTS:
                raise UnsafeUpdateUrlError("Release redirect is invalid")
            _validate_redirect_url(location)
            current = location
            continue
        if code == 404 and current == _API_URL:
            response.close()
            raise ReleaseNotFoundError("No published PageDrop release is available")
        if code >= 400:
            response.close()
            _raise_http_status(code, None)
        return response
    raise UnsafeUpdateUrlError("Release redirect limit exceeded")


def _stdlib_open(request: Request, timeout: float) -> _Response:
    return build_opener(_NoRedirect()).open(request, timeout=timeout)  # type: ignore[return-value]


def _read_limited(response: _Response, limit: int, monotonic: Callable[[], float], started: float, deadline: float, cancel_event: threading.Event | None = None) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        _ensure_not_cancelled(cancel_event)
        _ensure_before_deadline(monotonic, started, deadline)
        try:
            chunk = response.read(min(_CHUNK_SIZE, limit + 1 - total))
        except (TimeoutError, OSError) as exc:
            raise UpdateNetworkError("Could not read the update service response") from exc
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise ReleaseDataError("Update service response is too large")
        chunks.append(chunk)


def _parse_checksum(content: bytes, installer_name: str) -> str:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReleaseDataError("Installer checksum is invalid") from exc
    entries = [line.split() for line in text.splitlines() if line.strip()]
    matches = [parts for parts in entries if len(parts) == 2 and parts[1].lstrip("*") == installer_name]
    if len(matches) != 1 or not _SHA256_RE.fullmatch(matches[0][0]):
        raise ReleaseDataError("Installer checksum is invalid")
    return matches[0][0]


def _download_to(release: ReleaseInfo, output, cancel_event: threading.Event | None, progress: ProgressCallback | None, opener: OpenUrl, monotonic: Callable[[], float]) -> None:  # type: ignore[no-untyped-def]
    started = monotonic()
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelledError("Update download was cancelled")
    try:
        response = _request(
            release.installer_url,
            opener,
            _DOWNLOAD_SOCKET_TIMEOUT,
            monotonic,
            started,
            _DOWNLOAD_DEADLINE,
            True,
        )
    except UpdateNetworkError as exc:
        raise UpdateDownloadError("Could not download the update installer") from exc
    total = 0
    digest = hashlib.sha256()
    if progress:
        progress(0, release.installer_size)
    try:
        while True:
            _ensure_before_deadline(monotonic, started, _DOWNLOAD_DEADLINE)
            if cancel_event is not None and cancel_event.is_set():
                raise UpdateCancelledError("Update download was cancelled")
            try:
                chunk = response.read(_CHUNK_SIZE)
            except (TimeoutError, OSError) as exc:
                raise UpdateDownloadError("Could not download the update installer") from exc
            if not chunk:
                break
            total += len(chunk)
            if total > release.installer_size:
                raise UpdateDownloadError("Downloaded installer is larger than expected")
            output.write(chunk)
            digest.update(chunk)
            if progress:
                progress(total, release.installer_size)
    finally:
        response.close()
    if total != release.installer_size or digest.hexdigest() != release.expected_sha256:
        raise UpdateDownloadError("Downloaded installer could not be verified")


def _ensure_before_deadline(monotonic: Callable[[], float], started: float, deadline: float) -> None:
    if monotonic() - started > deadline:
        raise UpdateTimeoutError("Update operation timed out")


def _ensure_not_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelledError("Update check was cancelled")


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    return getter(name) if getter else None


def _raise_http_error(error: HTTPError) -> None:
    _raise_http_status(error.code, error.headers)


def _raise_http_status(code: int, headers: object | None) -> None:
    if code == 429 or (code == 403 and _header(headers, "X-RateLimit-Remaining") == "0"):
        raise RateLimitedError(_retry_after(headers))
    raise UpdateNetworkError("Update service returned an error")


def _retry_after(headers: object | None) -> datetime | None:
    now = datetime.now(UTC)
    value = _header(headers, "Retry-After")
    if value and value.isdecimal():
        return now + timedelta(seconds=int(value))
    reset = _header(headers, "X-RateLimit-Reset")
    if reset and reset.isdecimal():
        return datetime.fromtimestamp(int(reset), UTC)
    return None


def _remove_owned(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
