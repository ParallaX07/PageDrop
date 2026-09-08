"""Release artifact and draft-publication regressions (no live GitHub calls)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_packaging
from publish_windows_release import Release, ReleaseError, publish_tested_pair


class FakeReleaseOperations:
    def __init__(
        self, releases: dict[str, Release] | None = None, files: dict[str, bytes] | None = None
    ) -> None:
        self.releases = releases or {}
        self.files = files or {}
        self.calls: list[tuple] = []
        self.fail_upload = False

    def get(self, tag: str) -> Release | None:
        self.calls.append(("get", tag))
        return self.releases.get(tag)

    def create_draft(self, tag: str, title: str) -> None:
        self.calls.append(("create", tag, title))
        self.releases[tag] = Release(tag, True, frozenset())

    def delete_asset(self, tag: str, name: str) -> None:
        self.calls.append(("delete", tag, name))
        release = self.releases[tag]
        self.releases[tag] = Release(tag, release.draft, release.assets - {name})
        self.files.pop(name, None)

    def upload(self, tag: str, paths: list[Path]) -> None:
        self.calls.append(("upload", tag, tuple(path.name for path in paths)))
        if self.fail_upload:
            raise ReleaseError("simulated native upload failure")
        release = self.releases[tag]
        self.releases[tag] = Release(
            tag, release.draft, release.assets | {path.name for path in paths}
        )
        self.files.update({path.name: path.read_bytes() for path in paths})

    def download(self, tag: str, name: str, directory: Path) -> Path:
        self.calls.append(("download", tag, name))
        if name not in self.files:
            raise ReleaseError(f"missing mocked asset: {name}")
        path = directory / name
        path.write_bytes(self.files[name])
        return path

    def latest(self) -> Release | None:
        self.calls.append(("latest",))
        return self.releases.get("latest")

    def publish(self, tag: str, *, latest: bool) -> None:
        self.calls.append(("publish", tag, latest))


def _pair(tmp_path: Path) -> tuple[Path, Path, bytes, bytes]:
    installer = tmp_path / "PageDrop-1.2.3-Setup.exe"
    installer_bytes = b"tested installer bytes"
    installer.write_bytes(installer_bytes)
    checksum = Path(f"{installer}.sha256")
    checksum_bytes = (
        f"{hashlib.sha256(installer_bytes).hexdigest()}  {installer.name}\n".encode()
    )
    checksum.write_bytes(checksum_bytes)
    return installer, checksum, installer_bytes, checksum_bytes


def test_tag_mismatch_and_checksum_mismatch_are_rejected_before_release_calls(tmp_path):
    installer, checksum, _, _ = _pair(tmp_path)
    operations = FakeReleaseOperations()

    with pytest.raises(ReleaseError, match="names do not match"):
        publish_tested_pair(operations, tag="v1.2.4", installer=installer, checksum=checksum)
    with pytest.raises(ReleaseError, match="Invalid release tag"):
        publish_tested_pair(operations, tag="release-1.2.3", installer=installer, checksum=checksum)

    checksum.write_text("0" * 64 + f"  {installer.name}\n", encoding="ascii")
    with pytest.raises(ReleaseError, match="checksum"):
        publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum)
    assert operations.calls == []


def test_missing_installer_output_and_frozen_metadata_fail_packaging_checks(tmp_path, monkeypatch):
    version = check_packaging.read_version()
    monkeypatch.setattr(check_packaging, "ROOT", tmp_path)
    output = tmp_path / "installer" / "Output"
    output.mkdir(parents=True)
    (output / f"PageDrop-{version}-Setup.exe.sha256").write_text("missing", encoding="ascii")
    with pytest.raises(AssertionError, match="missing non-empty installer"):
        check_packaging._assert_installer_if_present(version)

    bundle = tmp_path / "dist" / "pagedrop"
    data = bundle / "_internal"
    (data / "pagedrop" / "assets" / "icons").mkdir(parents=True)
    (bundle / "pagedrop.exe").write_bytes(b"exe")
    (data / "THIRD_PARTY_NOTICES.md").write_text("notices", encoding="utf-8")
    (data / "pagedrop" / "assets" / "icons" / "icon.svg").write_text("svg", encoding="utf-8")
    with pytest.raises(AssertionError, match="METADATA"):
        check_packaging._assert_onedir_dist_if_present()


def test_partial_draft_retry_replaces_only_mismatched_asset(tmp_path):
    installer, checksum, installer_bytes, _ = _pair(tmp_path)
    operations = FakeReleaseOperations(
        {"v1.2.3": Release("v1.2.3", True, frozenset({installer.name, checksum.name}))},
        {installer.name: installer_bytes, checksum.name: b"wrong checksum\n"},
    )

    publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum)

    assert ("delete", "v1.2.3", checksum.name) in operations.calls
    assert ("delete", "v1.2.3", installer.name) not in operations.calls
    assert ("upload", "v1.2.3", (checksum.name,)) in operations.calls
    assert ("publish", "v1.2.3", True) in operations.calls


def test_published_release_and_failed_upload_never_reach_publication(tmp_path):
    installer, checksum, _, _ = _pair(tmp_path)
    published = FakeReleaseOperations({"v1.2.3": Release("v1.2.3", False, frozenset())})
    with pytest.raises(ReleaseError, match="already published"):
        publish_tested_pair(published, tag="v1.2.3", installer=installer, checksum=checksum)
    assert not any(call[0] == "publish" for call in published.calls)

    failing = FakeReleaseOperations()
    failing.fail_upload = True
    with pytest.raises(ReleaseError, match="upload failure"):
        publish_tested_pair(failing, tag="v1.2.3", installer=installer, checksum=checksum)
    assert not any(call[0] == "publish" for call in failing.calls)


def test_failed_build_job_cannot_schedule_publish_job():
    workflow = (ROOT / ".github" / "workflows" / "release-windows.yml").read_text(
        encoding="utf-8"
    )
    build, publish = workflow.split("  publish:\n", maxsplit=1)
    assert "needs: build" in publish
    assert ".\\scripts\\build_windows_installer.ps1 -Release" in build
    assert "if ($LASTEXITCODE -ne 0)" in build
