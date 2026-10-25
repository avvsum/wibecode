"""Связка окна Shorts Studio с программой: ShellWindow <-> RenderWorker в отдельном QThread.

Логику генерации, рендера и озвучки окно берёт из RenderWorker как есть, поэтому изменения
в воркере, api и llm работают здесь без правок. Новые настройки и доп. результаты — в features.py.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Slot
from PySide6.QtGui import QDesktopServices

from src.ui.features import EXTRAS
from src.ui.shell import ShellWindow
from src.ui.worker import RenderWorker

OUTPUT_DIR = Path.home() / "Videos" / "Shorts Studio"


def scene_dicts(spec) -> tuple[list, float]:
    """Spec (pydantic у A или dataclass в заглушках) -> сцены словарями, как в контракте JSON."""
    scenes = [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in spec.scenes]
    return scenes, float(spec.duration)


def reveal(path: str) -> None:
    if sys.platform == "win32" and path and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        folder = os.path.dirname(path) if path else str(OUTPUT_DIR)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


class _ExtraRelay(QObject):
    """Принимает (text, ok) из потока воркера в главном потоке и показывает карточку."""

    def __init__(self, window: ShellWindow, title: str, parent: QObject):
        super().__init__(parent)
        self._window, self._title = window, title

    @Slot(str, bool)
    def show(self, text: str, ok: bool) -> None:
        self._window.show_extra(self._title, text, ok)


class AppController(QObject):
    def __init__(self, window: ShellWindow):
        super().__init__(window)
        self.w = window
        self._thread = self._worker = None
        self._scenes, self._duration, self._out_path = [], 0.0, ""
        window.render_requested.connect(self.start)
        window.cancel_requested.connect(self.cancel)
        window.reveal_requested.connect(reveal)
        window.about_to_close.connect(self.shutdown)

    @Slot(str, str, dict)
    def start(self, text: str, mode: str, options: dict) -> None:
        if self._thread is not None:
            return
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._out_path = str(OUTPUT_DIR / f"shorts_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
        self._scenes, self._duration = [], 0.0
        self.w.set_generating()

        thread = QThread(self)
        worker = RenderWorker(text, self._out_path, mode, **options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.spec_ready.connect(self._on_spec)
        worker.frames.connect(self._on_frames)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        for extra in EXTRAS:  # доп. результат появится сам, как только у воркера будет такой сигнал
            signal = getattr(worker, extra.signal, None)
            if signal is not None:
                signal.connect(_ExtraRelay(self.w, extra.title, thread).show)
        for done in (worker.finished, worker.failed, worker.cancelled):
            done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._thread, self._worker = thread, worker
        thread.start()

    @Slot()
    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    @Slot()
    def shutdown(self) -> None:
        """Окно закрывается: прерываем рендер и ждём поток, чтобы он не умер посреди работы."""
        if self._thread is not None:
            self._worker.cancel()
            self._thread.quit()
            self._thread.wait()

    @Slot(object)
    def _on_spec(self, spec) -> None:
        self._scenes, self._duration = scene_dicts(spec)

    @Slot(int, int)
    def _on_frames(self, done: int, total: int) -> None:
        self.w.set_rendering(done, total, self._scenes, self._duration)

    @Slot(str)
    def _on_finished(self, path: str) -> None:
        self.w.set_done(path, self._scenes, self._duration)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        if self._scenes and os.path.exists(self._out_path):
            # Видео уже отрендерено (не удалась, например, озвучка): не теряем его.
            self.w.set_done(self._out_path, self._scenes, self._duration)
            self.w.set_warning(message)
        else:
            self.w.set_error(message)

    @Slot()
    def _on_cancelled(self) -> None:
        self.w.set_cancelled()

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread.deleteLater()
        self._thread = self._worker = None
