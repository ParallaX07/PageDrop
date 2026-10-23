"""Release artifact and draft-publication regressions (no live GitHub calls)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_packaging
import publish_release
from publish_release import GhReleaseOperations, Release, ReleaseError, publish_tested_pair


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

    def create_draft(self, tag: str, title: str, notes_file: Path) -> None:
        self.calls.append(("create", tag, title))
        self.releases[tag] = Release(tag, True, frozenset(), notes_file.read_text(encoding="utf-8"))

    def edit_notes(self, tag: str, notes_file: Path) -> None:
        notes = notes_file.read_text(encoding="utf-8")
        self.calls.append(("edit_notes", tag, notes))
        release = self.releases[tag]
        self.releases[tag] = Release(tag, release.draft, release.assets, notes)

    def delete_asset(self, tag: str, name: str) -> None:
        self.calls.append(("delete", tag, name))
        release = self.releases[tag]
        self.releases[tag] = Release(tag, release.draft, release.assets - {name}, release.notes)
        self.files.pop(name, None)

    def upload(self, tag: str, paths: list[Path]) -> None:
        self.calls.append(("upload", tag, tuple(path.name for path in paths)))
        if self.fail_upload:
            raise ReleaseError("simulated native upload failure")
        release = self.releases[tag]
        self.releases[tag] = Release(
            tag, release.draft, release.assets | {path.name for path in paths}, release.notes
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


def _release_files(tmp_path: Path) -> dict[str, Path]:
    appimage = tmp_path / "PageDrop-1.2.3-x86_64.AppImage"
    appimage.write_bytes(b"tested appimage bytes")
    zsync = tmp_path / f"{appimage.name}.zsync"
    zsync.write_bytes(b"zsync data")
    checksum = Path(f"{appimage}.sha256")
    checksum.write_bytes(f"{hashlib.sha256(appimage.read_bytes()).hexdigest()}  {appimage.name}\n".encode("ascii"))
    notes = tmp_path / "v1.2.3.md"
    notes.write_text("# PageDrop 1.2.3\n", encoding="utf-8")
    return {"appimage": appimage, "zsync": zsync, "appimage_checksum": checksum, "notes_file": notes}


def _publish(operations, installer, checksum, tmp_path):
    publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **_release_files(tmp_path))


def test_tag_mismatch_and_checksum_mismatch_are_rejected_before_release_calls(tmp_path):
    installer, checksum, _, _ = _pair(tmp_path)
    operations = FakeReleaseOperations()

    with pytest.raises(ReleaseError, match="names do not match"):
        publish_tested_pair(operations, tag="v1.2.4", installer=installer, checksum=checksum, **_release_files(tmp_path))
    with pytest.raises(ReleaseError, match="Invalid release tag"):
        publish_tested_pair(operations, tag="release-1.2.3", installer=installer, checksum=checksum, **_release_files(tmp_path))

    checksum.write_text("0" * 64 + f"  {installer.name}\n", encoding="ascii")
    with pytest.raises(ReleaseError, match="checksum"):
        _publish(operations, installer, checksum, tmp_path)
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

    _publish(operations, installer, checksum, tmp_path)

    assert ("delete", "v1.2.3", checksum.name) in operations.calls
    assert ("delete", "v1.2.3", installer.name) not in operations.calls
    uploaded = next(call[2] for call in operations.calls if call[0] == "upload")
    assert checksum.name in uploaded and "latest.json" in uploaded
    assert "PageDrop-1.2.3-x86_64.AppImage" in uploaded
    assert "PageDrop-1.2.3-x86_64.AppImage.zsync" in uploaded
    assert ("publish", "v1.2.3", True) in operations.calls


def test_github_draft_release_is_found_when_tag_endpoint_returns_not_found(monkeypatch):
    operations = GhReleaseOperations("ParallaX07/PageDrop")

    def run(*args):
        if args[1].endswith("/tags/v1.2.3"):
            raise ReleaseError("HTTP 404: Not Found")
        assert args == ("api", "repos/ParallaX07/PageDrop/releases?per_page=100")
        return '[{"tag_name": "v1.2.3", "draft": true, "assets": []}]'

    monkeypatch.setattr(operations, "_run", run)

    assert operations.get("v1.2.3") == Release("v1.2.3", True, frozenset())


def test_gh_release_operations_decodes_github_output_as_utf8(monkeypatch):
    captured: dict[str, object] = {}

    def run(*args, **kwargs):
        captured.update(kwargs)
        return type("Result", (), {"stdout": "[]"})()

    monkeypatch.setattr(publish_release.subprocess, "run", run)

    assert GhReleaseOperations("ParallaX07/PageDrop")._run("api", "releases") == "[]"
    assert captured["encoding"] == "utf-8"


def test_github_release_create_and_edit_use_the_checked_in_notes_file(monkeypatch, tmp_path):
    operations = GhReleaseOperations("ParallaX07/PageDrop")
    calls = []
    monkeypatch.setattr(operations, "_run", lambda *args: calls.append(args) or "")
    notes = tmp_path / "v1.2.3.md"
    notes.write_text("Release notes", encoding="utf-8")

    operations.create_draft("v1.2.3", "PageDrop 1.2.3", notes)
    operations.edit_notes("v1.2.3", notes)

    assert calls == [
        ("release", "create", "v1.2.3", "--repo", "ParallaX07/PageDrop", "--draft", "--title", "PageDrop 1.2.3", "--notes-file", str(notes)),
        ("release", "edit", "v1.2.3", "--repo", "ParallaX07/PageDrop", "--notes-file", str(notes)),
    ]


def test_published_release_and_failed_upload_never_reach_publication(tmp_path):
    installer, checksum, _, _ = _pair(tmp_path)
    published = FakeReleaseOperations({"v1.2.3": Release("v1.2.3", False, frozenset())})
    with pytest.raises(ReleaseError, match="already published"):
        _publish(published, installer, checksum, tmp_path)
    assert not any(call[0] == "publish" for call in published.calls)

    failing = FakeReleaseOperations()
    failing.fail_upload = True
    with pytest.raises(ReleaseError, match="upload failure"):
        _publish(failing, installer, checksum, tmp_path)
    assert not any(call[0] == "publish" for call in failing.calls)


def test_failed_build_job_cannot_schedule_publish_job():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    build, publish = workflow.split("  publish:\n", maxsplit=1)
    assert "needs: [release-notes, build-windows, build-linux]" in publish
    assert ".\\scripts\\build_windows_installer.ps1 -Release" in build
    assert "if ($LASTEXITCODE -ne 0)" in build
    assert "build-linux:" in build and "build-windows:" in build
    assert "release-notes/${GITHUB_REF_NAME}.md" in publish


def test_installer_build_rejects_stale_frozen_version_before_compiling():
    script = (ROOT / "scripts" / "build_windows_installer.ps1").read_text(encoding="utf-8")
    assert "scripts/check_packaging.py" in script
    assert script.index("scripts/check_packaging.py") < script.index("Compiling installer")


def test_installer_removes_stale_pagedrop_metadata_before_copying_bundle():
    script = (ROOT / "installer" / "windows.iss").read_text(encoding="utf-8")
    cleanup = script.split("[InstallDelete]", 1)[1].split("[Files]", 1)[0]
    for path in (r"{app}\_internal\pagedrop-*.dist-info", r"{app}\pagedrop-*.dist-info"):
        assert f'Type: filesandordirs; Name: "{path}"' in cleanup


def test_manifest_matches_tested_installer_and_checked_in_notes(tmp_path):
    installer, checksum, payload, _ = _pair(tmp_path)
    files = _release_files(tmp_path)
    notes = "Improved café rendering — বাংলা"
    files["notes_file"].write_text(notes, encoding="utf-8")
    operations = FakeReleaseOperations({"v1.2.3": Release("v1.2.3", True, frozenset(), "old notes")})
    publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **files)
    manifest = operations.files["latest.json"]
    assert json.loads(manifest) == {
        "schema_version": 1, "version": "1.2.3", "installer_size": len(payload),
        "installer_sha256": hashlib.sha256(payload).hexdigest(), "notes": notes,
    }
    operations.calls.clear()
    publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **files)
    assert operations.files["latest.json"] == manifest
    assert not any(call[0] in {"upload", "delete"} for call in operations.calls)


def test_notes_version_placeholder_is_substituted_in_release_body_and_manifest(tmp_path):
    installer, checksum, payload, _ = _pair(tmp_path)
    files = _release_files(tmp_path)
    files["notes_file"].write_text("Source: tag v{{version}}", encoding="utf-8")
    operations = FakeReleaseOperations()
    publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **files)
    expected_notes = "Source: tag v1.2.3"
    assert operations.releases["v1.2.3"].notes == expected_notes
    assert json.loads(operations.files["latest.json"])["notes"] == expected_notes


def test_missing_or_empty_notes_fail_before_release_calls(tmp_path):
    installer, checksum, _, _ = _pair(tmp_path)
    files = _release_files(tmp_path)
    files["notes_file"].write_text(" \n\t", encoding="utf-8")
    operations = FakeReleaseOperations()
    with pytest.raises(ReleaseError, match="missing or empty"):
        publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **files)
    assert operations.calls == []


def test_appimage_checksum_mismatch_fails_before_release_calls(tmp_path):
    installer, checksum, _, _ = _pair(tmp_path)
    files = _release_files(tmp_path)
    files["appimage_checksum"].write_text("0" * 64 + "  wrong.AppImage\n", encoding="ascii")
    operations = FakeReleaseOperations()
    with pytest.raises(ReleaseError, match="checksum does not match AppImage"):
        publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **files)
    assert operations.calls == []


def test_mismatched_manifest_is_replaced_and_verified(tmp_path):
    installer, checksum, payload, digest = _pair(tmp_path)
    operations = FakeReleaseOperations(
        {"v1.2.3": Release("v1.2.3", True, frozenset({installer.name, checksum.name, "latest.json"}))},
        {installer.name: payload, checksum.name: digest, "latest.json": b"wrong"},
    )
    _publish(operations, installer, checksum, tmp_path)
    assert ("delete", "v1.2.3", "latest.json") in operations.calls
    uploaded = next(call[2] for call in operations.calls if call[0] == "upload")
    assert "latest.json" in uploaded


def test_corrupt_uploaded_manifest_never_publishes(tmp_path):
    installer, checksum, _, _ = _pair(tmp_path)
    class CorruptUpload(FakeReleaseOperations):
        def upload(self, tag, paths):
            super().upload(tag, paths)
            self.files["latest.json"] = b"corrupted"
    operations = CorruptUpload()
    with pytest.raises(ReleaseError, match="latest.json"):
        _publish(operations, installer, checksum, tmp_path)
    assert not any(call[0] == "publish" for call in operations.calls)


def test_linux_assets_and_notes_are_reverified_on_retry(tmp_path):
    installer, checksum, installer_bytes, installer_checksum = _pair(tmp_path)
    files = _release_files(tmp_path)
    operations = FakeReleaseOperations()
    publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **files)

    names = operations.releases["v1.2.3"].assets
    assert names == {
        installer.name,
        checksum.name,
        files["appimage"].name,
        files["zsync"].name,
        files["appimage_checksum"].name,
        "latest.json",
    }
    assert operations.files[installer.name] == installer_bytes
    assert operations.files[checksum.name] == installer_checksum
    assert ("edit_notes", "v1.2.3", files["notes_file"].read_text(encoding="utf-8")) in operations.calls
    operations.calls.clear()
    publish_tested_pair(operations, tag="v1.2.3", installer=installer, checksum=checksum, **files)
    assert not any(call[0] in {"upload", "delete"} for call in operations.calls)
