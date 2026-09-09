"""Small QRunnable bridge for editor save and folder-export snapshots."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from pagedrop.core.jobs import CancelToken, JobCancelledError, JobSpec, SerializedJobRunner
from pagedrop.core.page_extractor import extract_page_refs_to_folder

_POOL: QThreadPool | None = None
_SIGNALS: list[QObject] = []


def editor_job_pool() -> QThreadPool:
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(1)
        _POOL.setObjectName("PageDropEditorJobPool")
    return _POOL


class EditorJobWorker(QRunnable):
    class Signals(QObject):
        progress = pyqtSignal(float, str)
        succeeded = pyqtSignal(object)
        cancelled = pyqtSignal()
        failed = pyqtSignal(str)

    def __init__(self, work: Callable[[Callable[[float, str], None]], object]) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._work = work
        self.setAutoDelete(True)

    @classmethod
    def save(
        cls, runner: SerializedJobRunner, spec: JobSpec, cancel: CancelToken, credentials
    ) -> EditorJobWorker:
        return cls(lambda progress: runner.run(spec, credentials=credentials, progress=progress, cancel=cancel))

    @classmethod
    def export(
        cls,
        refs,
        output_dir: Path,
        base_name: str,
        passwords: dict[str, str],
        cancel: CancelToken,
        temp_manager,
    ) -> EditorJobWorker:
        def work(progress: Callable[[float, str], None]) -> object:
            progress(0.0, "Extracting pages…")
            paths = extract_page_refs_to_folder(
                refs, output_dir, base_name, passwords=passwords, cancel=cancel,
                temp_manager=temp_manager,
            )
            progress(1.0, "Extracted pages")
            return paths
        return cls(work)

    def run(self) -> None:
        try:
            result = self._work(lambda fraction, message: self.signals.progress.emit(fraction, message))
        except JobCancelledError:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)


def start_editor_worker(worker: EditorJobWorker) -> None:
    _SIGNALS.append(worker.signals)
    editor_job_pool().start(worker)


def release_editor_signals(signals: QObject) -> None:
    try:
        _SIGNALS.remove(signals)
    except ValueError:
        pass
