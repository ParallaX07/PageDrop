"""Publish a tested installer, checksum, and verified static update manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

REPOSITORY = "ParallaX07/PageDrop"
_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class ReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    tag: str
    draft: bool
    assets: frozenset[str]
    notes: str = ""


class ReleaseOperations(Protocol):
    def get(self, tag: str) -> Release | None: ...

    def create_draft(self, tag: str, title: str) -> None: ...

    def delete_asset(self, tag: str, name: str) -> None: ...

    def upload(self, tag: str, paths: list[Path]) -> None: ...

    def download(self, tag: str, name: str, directory: Path) -> Path: ...

    def latest(self) -> Release | None: ...

    def publish(self, tag: str, *, latest: bool) -> None: ...


class GhReleaseOperations:
    def __init__(self, repository: str) -> None:
        self.repository = repository

    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["gh", *args], text=True, capture_output=True, check=True
            )
        except subprocess.CalledProcessError as exc:
            raise ReleaseError(exc.stderr.strip() or "gh command failed") from exc
        return result.stdout

    def _get(self, path: str) -> dict | None:
        try:
            return json.loads(self._run("api", path))
        except ReleaseError as exc:
            if "404" in str(exc) or "Not Found" in str(exc):
                return None
            raise

    @staticmethod
    def _release(value: dict) -> Release:
        tag = value.get("tag_name")
        draft = value.get("draft")
        assets = value.get("assets")
        if not isinstance(tag, str) or not isinstance(draft, bool) or not isinstance(assets, list):
            raise ReleaseError("GitHub returned malformed release data")
        names = [asset.get("name") for asset in assets if isinstance(asset, dict)]
        if len(names) != len(assets) or any(not isinstance(name, str) for name in names):
            raise ReleaseError("GitHub returned malformed release assets")
        notes = value.get("body")
        if notes is None:
            notes = ""
        if not isinstance(notes, str):
            raise ReleaseError("GitHub returned malformed release notes")
        return Release(tag, draft, frozenset(names), notes)

    def get(self, tag: str) -> Release | None:
        value = self._get(f"repos/{self.repository}/releases/tags/{tag}")
        if value is not None:
            return self._release(value)
        releases = json.loads(self._run(f"api", f"repos/{self.repository}/releases?per_page=100"))
        if not isinstance(releases, list):
            raise ReleaseError("GitHub returned malformed release list")
        for release in releases:
            if isinstance(release, dict) and release.get("tag_name") == tag:
                return self._release(release)
        return None

    def create_draft(self, tag: str, title: str) -> None:
        self._run("release", "create", tag, "--repo", self.repository, "--draft", "--title", title, "--generate-notes")

    def delete_asset(self, tag: str, name: str) -> None:
        self._run("release", "delete-asset", tag, name, "--repo", self.repository, "--yes")

    def upload(self, tag: str, paths: list[Path]) -> None:
        self._run("release", "upload", tag, *(str(path) for path in paths), "--repo", self.repository)

    def download(self, tag: str, name: str, directory: Path) -> Path:
        self._run("release", "download", tag, "--repo", self.repository, "--pattern", name, "--dir", str(directory), "--clobber")
        path = directory / name
        if not path.is_file():
            raise ReleaseError(f"GitHub did not download expected asset: {name}")
        return path

    def latest(self) -> Release | None:
        value = self._get(f"repos/{self.repository}/releases/latest")
        return None if value is None else self._release(value)

    def publish(self, tag: str, *, latest: bool) -> None:
        self._run("release", "edit", tag, "--repo", self.repository, "--draft=false", f"--latest={str(latest).lower()}")


def _version(tag: str) -> tuple[int, int, int]:
    match = _TAG_RE.fullmatch(tag)
    if not match:
        raise ReleaseError(f"Invalid release tag: {tag}")
    return tuple(int(part) for part in match.groups())


def _expected_pair(installer: Path, checksum: Path, tag: str) -> dict[str, bytes]:
    version = ".".join(map(str, _version(tag)))
    expected_installer = f"PageDrop-{version}-Setup.exe"
    if installer.name != expected_installer or checksum.name != f"{expected_installer}.sha256":
        raise ReleaseError("Installer/checksum names do not match the release tag")
    if not installer.is_file() or installer.stat().st_size <= 0 or not checksum.is_file():
        raise ReleaseError("Tested installer/checksum pair is incomplete")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    expected_checksum = f"{digest}  {installer.name}\n".encode("ascii")
    if checksum.read_bytes() != expected_checksum:
        raise ReleaseError("Tested checksum does not match installer bytes")
    return {installer.name: installer.read_bytes(), checksum.name: expected_checksum}


def publish_tested_pair(
    operations: ReleaseOperations, *, tag: str, installer: Path, checksum: Path
) -> None:
    expected = _expected_pair(installer, checksum, tag)
    release = operations.get(tag)
    if release is not None and not release.draft:
        raise ReleaseError(f"Release {tag} is already published; refusing to mutate it")
    if release is None:
        operations.create_draft(tag, f"PageDrop {'.'.join(map(str, _version(tag)))}")
        release = operations.get(tag)
    if release is None or not release.draft or release.tag != tag:
        raise ReleaseError("Draft release identity changed")

    paths = {installer.name: installer, checksum.name: checksum}
    with tempfile.TemporaryDirectory(prefix="pagedrop-release-") as temporary:
        directory = Path(temporary)
        manifest = {
            "schema_version": 1,
            "version": ".".join(map(str, _version(tag))),
            "installer_size": len(expected[installer.name]),
            "installer_sha256": hashlib.sha256(expected[installer.name]).hexdigest(),
            "notes": release.notes,
        }
        expected["latest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(expected["latest.json"]) > 1024 * 1024:
            raise ReleaseError("Update manifest exceeds the updater size limit")
        # Keep generated bytes separate from downloaded verification copies.
        generated = directory / "generated"
        generated.mkdir()
        paths["latest.json"] = generated / "latest.json"
        paths["latest.json"].write_bytes(expected["latest.json"])
        upload: list[Path] = []
        for name, expected_bytes in expected.items():
            if name not in release.assets:
                upload.append(paths[name])
                continue
            if operations.download(tag, name, directory).read_bytes() != expected_bytes:
                operations.delete_asset(tag, name)
                upload.append(paths[name])
        if upload:
            operations.upload(tag, upload)
        for name, expected_bytes in expected.items():
            if operations.download(tag, name, directory).read_bytes() != expected_bytes:
                raise ReleaseError(f"Uploaded {name} differs from tested bytes")

    latest = operations.latest()
    is_latest = latest is None or _version(tag) > _version(latest.tag)
    final = operations.get(tag)
    if final is None or not final.draft or final.tag != tag or final.notes != release.notes:
        raise ReleaseError("Draft changed before publication")
    operations.publish(tag, latest=is_latest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--checksum", required=True, type=Path)
    parser.add_argument("--repository", default=REPOSITORY)
    args = parser.parse_args()
    if args.repository != REPOSITORY:
        raise SystemExit(f"Refusing to publish outside {REPOSITORY}")
    try:
        publish_tested_pair(
            GhReleaseOperations(args.repository),
            tag=args.tag,
            installer=args.installer,
            checksum=args.checksum,
        )
    except ReleaseError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
