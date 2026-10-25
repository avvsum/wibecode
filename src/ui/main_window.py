import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from src.ui.worker import RenderWorker

OUTPUT_DIR = Path(tempfile.gettempdir()) / "shorts-maker"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shorts Maker")
        self.resize(900, 640)
        self._thread = None

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Опишите ролик: о чём он, какие кадры и цифры показать…")
        self.mode_box = QComboBox()
        self.mode_box.addItem("2D", "2d")
        self.mode_box.addItem("3D", "3d")
        self.render_button = QPushButton("Рендер")
        self.render_button.clicked.connect(self.start_render)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        self.video = QVideoWidget()
        self.video.setMinimumSize(270, 480)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(self._on_player_error)
        self.play_button = QPushButton("▶ / ❚❚")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._toggle_play)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Render mode:"))
        mode_row.addWidget(self.mode_box)
        mode_row.addStretch()
        buttons = QHBoxLayout()
        buttons.addWidget(self.render_button, 1)
        buttons.addWidget(self.cancel_button)
        left = QVBoxLayout()
        left.addWidget(self.input)
        left.addLayout(mode_row)
        left.addWidget(self.progress_bar)
        left.addLayout(buttons)
        right = QVBoxLayout()
        right.addWidget(self.video, 1)
        right.addWidget(self.play_button)
        root = QHBoxLayout()
        root.addLayout(left, 1)
        root.addLayout(right)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._set_status("Готов к работе")

    def _set_status(self, text: str, error: bool = False) -> None:
        self.statusBar().setStyleSheet("color: #c62828;" if error else "")
        self.statusBar().showMessage(text)

    @Slot()
    def start_render(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            self._set_status("Введите описание ролика", error=True)
            return
        if self._thread is not None:
            return

        # Плеер держит файл открытым, поэтому отпускаем старое видео и пишем в новый файл.
        self.player.stop()
        self.player.setSource(QUrl())
        self.play_button.setEnabled(False)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = str(OUTPUT_DIR / f"render_{time.strftime('%Y%m%d_%H%M%S')}.mp4")

        self.render_button.setEnabled(False)
        self.mode_box.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # пока LLM пишет сценарий, число кадров неизвестно
        self.progress_bar.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)
        self._thread = QThread(self)
        self._worker = RenderWorker(text, out_path, self.mode_box.currentData())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._set_status)
        self._worker.frames.connect(self._on_frames)
        self._worker.finished.connect(self._on_rendered)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        for done_signal in (self._worker.finished, self._worker.failed, self._worker.cancelled):
            done_signal.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    @Slot(str)
    def _on_rendered(self, path: str) -> None:
        self.player.setSource(QUrl.fromLocalFile(path))
        self.play_button.setEnabled(True)
        self.player.play()
        self._set_status(f"Готово: {path}")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_status(message, error=True)

    @Slot(int, int)
    def _on_frames(self, done: int, total: int) -> None:
        if total <= 0:
            self.progress_bar.setRange(0, 0)
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        # На последнем кадре идёт сборка MP4: done стоит на total - 1 до самого конца.
        label = "Сборка видео…" if total > 1 and done == total - 1 else f"Кадр {done} из {total}"
        self.progress_bar.setFormat(f"{label}  %p%")

    @Slot()
    def _on_cancel_clicked(self) -> None:
        if self._thread is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self._set_status("Отмена…")

    @Slot()
    def _on_cancelled(self) -> None:
        self._set_status("Рендер отменён")

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread.deleteLater()
        self._thread = None
        self.render_button.setEnabled(True)
        self.mode_box.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.cancel_button.setVisible(False)

    @Slot()
    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    @Slot()
    def _on_player_error(self) -> None:
        self._set_status(f"Ошибка превью: {self.player.errorString()}", error=True)

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            # Рендер прерывается на ближайшем on_progress; запрос к LLM придётся дождаться.
            self._worker.cancel()
            self._thread.quit()
            self._thread.wait()
        super().closeEvent(event)
