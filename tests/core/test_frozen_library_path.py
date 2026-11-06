"""Frozen Linux builds must not leak the bundled library path to child programs."""

from __future__ import annotations

import os
import sys

import pytest

from pagedrop.core.backends.process_tree import frozen_child_env, popen_owned
from pagedrop.main import restore_inherited_library_path

BUNDLE = "/opt/pagedrop/_internal"


def _restore(environ, *, frozen=True, platform="linux"):
    restore_inherited_library_path(environ, frozen=frozen, platform=platform)
    return environ


def test_frozen_linux_restores_the_saved_original():
    env = {"LD_LIBRARY_PATH": f"{BUNDLE}:/usr/lib/x", "LD_LIBRARY_PATH_ORIG": "/usr/lib/x"}
    assert _restore(env)["LD_LIBRARY_PATH"] == "/usr/lib/x"


def test_frozen_linux_restores_an_empty_original():
    env = {"LD_LIBRARY_PATH": BUNDLE, "LD_LIBRARY_PATH_ORIG": ""}
    assert _restore(env)["LD_LIBRARY_PATH"] == ""


def test_frozen_linux_without_original_removes_the_variable():
    env = {"LD_LIBRARY_PATH": BUNDLE, "PATH": "/usr/bin"}
    assert _restore(env) == {"PATH": "/usr/bin"}


def test_frozen_linux_without_any_library_path_is_unchanged():
    assert _restore({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


@pytest.mark.parametrize(("frozen", "platform"), [(False, "linux"), (True, "win32"), (True, "darwin")])
def test_other_setups_are_left_alone(frozen, platform):
    env = {"LD_LIBRARY_PATH": BUNDLE, "LD_LIBRARY_PATH_ORIG": "/usr/lib/x"}
    assert _restore(dict(env), frozen=frozen, platform=platform) == env


def test_child_started_after_restoration_does_not_see_the_bundled_path(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{BUNDLE}:/usr/lib/x")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/x")
    restore_inherited_library_path(os.environ, frozen=True, platform="linux")
    code = "import os; print(os.environ.get('LD_LIBRARY_PATH', 'unset'))"
    proc = popen_owned([sys.executable, "-c", code])
    out, _err = proc.communicate(timeout=30)
    assert out.strip() == "/usr/lib/x"

    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    monkeypatch.setenv("LD_LIBRARY_PATH", BUNDLE)
    restore_inherited_library_path(os.environ, frozen=True, platform="linux")
    out, _err = popen_owned([sys.executable, "-c", code]).communicate(timeout=30)
    assert out.strip() == "unset"


def test_own_helpers_get_the_bundle_directory_back(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", BUNDLE, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/lib/x")
    assert frozen_child_env()["LD_LIBRARY_PATH"] == f"{BUNDLE}:/usr/lib/x"
    monkeypatch.delenv("LD_LIBRARY_PATH")
    assert frozen_child_env()["LD_LIBRARY_PATH"] == BUNDLE


def test_own_helpers_inherit_as_is_when_not_frozen_linux(monkeypatch):
    assert frozen_child_env() is None  # test runs are never frozen
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert frozen_child_env() is None


def test_compress_and_verify_helpers_start_with_the_frozen_child_env(monkeypatch, tmp_path):
    from pagedrop.core import optimize_secure, redact

    sentinel = {"LD_LIBRARY_PATH": BUNDLE}
    seen: dict[str, object] = {}

    def fake(name):
        def _spawn(_argv, **kwargs):
            seen[name] = kwargs.get("env")
            raise OSError("stop here")

        return _spawn

    monkeypatch.setattr(optimize_secure, "frozen_child_env", lambda: sentinel)
    monkeypatch.setattr(redact, "frozen_child_env", lambda: sentinel)
    monkeypatch.setattr(optimize_secure, "popen_owned", fake("compress"))
    monkeypatch.setattr(redact, "popen_owned", fake("verify"))

    with pytest.raises(optimize_secure.CompressWorkerError):
        optimize_secure.compress_pdf_lossy_in_child(
            str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf"), optimize_secure.LOSSY_PROFILES["screen"]
        )
    report = redact.verify_redacted_pdf_fresh_process(tmp_path / "a.pdf")
    assert report.failures
    assert seen == {"compress": sentinel, "verify": sentinel}
