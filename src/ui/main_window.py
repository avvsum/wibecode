import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from src.ui.worker import PublishWorker, RenderWorker

OUTPUT_DIR = Path(tempfile.gettempdir()) / "shorts-maker"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shorts Maker")
        self.resize(900, 640)
        self._thread = None
        self._video_path = None  # последний готовый ролик, его можно опубликовать
        self._metadata = None  # название, описание и теги от LLM для публикации

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Опишите ролик: о чём он, какие кадры и цифры показать…")
        self.mode_box = QComboBox()
        self.mode_box.addItem("2D", "2d")
        self.mode_box.addItem("3D", "3d")
        self.environment_box = QComboBox()
        for label, key in (
            ("Студия (исходная)", "studio"), ("Уютная комната", "room"),
            ("Лесная поляна", "forest"), ("Подземелье", "dungeon"),
            ("Космическая база", "space"), ("Городская площадь", "city"),
        ):
            self.environment_box.addItem(label, key)
        self.environment_box.setCurrentIndex(1)
        self.cast_box = QComboBox()
        for label, key in (
            ("Робот и девушка", "classic"), ("Рыцарь и маг", "knight_mage"),
            ("Два разбойника", "rogue_duo"), ("Варвар и маг", "barbarian_mage"),
            ("Лучник и рыцарь", "ranger_knight"),
        ):
            self.cast_box.addItem(label, key)
        self.cast_box.setCurrentIndex(1)
        self.voice_box = QComboBox()
        self.voice_box.addItem("Без озвучки", None)
        self.voice_box.addItem("ElevenLabs", "elevenlabs")
        self.voice_box.addItem("Chatterbox (локально)", "chatterbox")
        self.voice_box.setToolTip(
            "ElevenLabs: ключ в ELEVENLABS_API_KEY. "
            "Chatterbox: бесплатно на этом компьютере, pip install -r requirements-chatterbox.txt"
        )
        self.render_button = QPushButton("Рендер")
        self.render_button.clicked.connect(self.start_render)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.metadata_box = QPlainTextEdit()
        self.metadata_box.setReadOnly(True)
        self.metadata_box.setPlaceholderText("Здесь появятся название, описание и теги для YouTube")
        self.copy_button = QPushButton("Копировать для YouTube")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy_metadata)

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
        self.publish_button = QPushButton("Опубликовать на YouTube")
        self.publish_button.setEnabled(False)
        self.publish_button.setToolTip(
            "Нужен OAuth-клиент Desktop app из Google Cloud: ~/.shortsstudio/client_secret.json "
            "или путь в WIBECODE_YT_CLIENT_SECRET. Пока проект не прошёл аудит Google, "
            "YouTube публикует ролик как приватный."
        )
        self.publish_button.clicked.connect(self.start_publish)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Render mode:"))
        mode_row.addWidget(self.mode_box)
        mode_row.addWidget(QLabel("Озвучка:"))
        mode_row.addWidget(self.voice_box)
        mode_row.addStretch()
        self.scene_options = QWidget()
        scene_row = QHBoxLayout(self.scene_options)
        scene_row.setContentsMargins(0, 0, 0, 0)
        scene_row.addWidget(QLabel("Окружение:"))
        scene_row.addWidget(self.environment_box, 1)
        scene_row.addWidget(QLabel("Персонажи:"))
        scene_row.addWidget(self.cast_box, 1)
        self.scene_options.setVisible(False)
        self.mode_box.currentIndexChanged.connect(self._sync_scene_options)
        buttons = QHBoxLayout()
        buttons.addWidget(self.render_button, 1)
        buttons.addWidget(self.cancel_button)
        left = QVBoxLayout()
        left.addWidget(self.input, 2)
        left.addLayout(mode_row)
        left.addWidget(self.scene_options)
        left.addWidget(self.progress_bar)
        left.addLayout(buttons)
        left.addWidget(QLabel("YouTube: название, описание, теги"))
        left.addWidget(self.metadata_box, 1)
        left.addWidget(self.copy_button)
        right = QVBoxLayout()
        right.addWidget(self.video, 1)
        right.addWidget(self.play_button)
        right.addWidget(self.publish_button)
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

    def _sync_scene_options(self) -> None:
        self.scene_options.setVisible(self.mode_box.currentData() == "3d")

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
        self.metadata_box.clear()
        self.copy_button.setEnabled(False)
        self._video_path = None
        self._metadata = None
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = str(OUTPUT_DIR / f"render_{time.strftime('%Y%m%d_%H%M%S')}.mp4")

        self.render_button.setEnabled(False)
        self.mode_box.setEnabled(False)
        self.voice_box.setEnabled(False)
        self.scene_options.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # пока LLM пишет сценарий, число кадров неизвестно
        self.progress_bar.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)
        self._thread = QThread(self)
        self._worker = RenderWorker(
            text, out_path, self.mode_box.currentData(), self.voice_box.currentData(),
            environment=self.environment_box.currentData(), cast=self.cast_box.currentData(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._set_status)
        self._worker.frames.connect(self._on_frames)
        self._worker.metadata.connect(self._on_metadata)
        self._worker.metadata_ready.connect(self._on_metadata_ready)
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
        self._video_path = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.play_button.setEnabled(True)
        self.player.play()
        self._set_status(f"Готово: {path}")

    @Slot()
    def start_publish(self) -> None:
        if self._thread is not None or self._video_path is None:
            return
        text = self.input.toPlainText().strip()
        self.render_button.setEnabled(False)
        self.publish_button.setEnabled(False)
        self.mode_box.setEnabled(False)
        self.voice_box.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # до начала загрузки идёт вход в Google
        self.progress_bar.setVisible(True)
        self._set_status("Публикация на YouTube… При первом запуске откроется браузер для входа.")
        self._thread = QThread(self)
        meta = self._metadata  # без метаданных LLM: первая строка описания и весь текст
        self._worker = PublishWorker(
            self._video_path,
            title=meta.title if meta else text,
            description=meta.description if meta else text,
            tags=meta.tags if meta else (),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.uploaded.connect(self._on_uploaded)
        self._worker.finished.connect(self._on_published)
        self._worker.failed.connect(self._on_failed)
        for done_signal in (self._worker.finished, self._worker.failed):
            done_signal.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    @Slot(int, int)
    def _on_uploaded(self, sent: int, total: int) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(sent)
        self.progress_bar.setFormat("Загрузка на YouTube  %p%")

    @Slot(str)
    def _on_published(self, url: str) -> None:
        self._set_status(f"Опубликовано на YouTube: {url}")
        QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_status(message, error=True)

    @Slot(str, bool)
    def _on_metadata(self, text: str, ok: bool) -> None:
        self.metadata_box.setPlainText(text)
        self.copy_button.setEnabled(ok)

    @Slot(object)
    def _on_metadata_ready(self, meta) -> None:
        self._metadata = meta

    @Slot()
    def _copy_metadata(self) -> None:
        QGuiApplication.clipboard().setText(self.metadata_box.toPlainText())
        self._set_status("Название, описание и теги скопированы")

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
        self.voice_box.setEnabled(True)
        self.publish_button.setEnabled(self._video_path is not None)
        self.scene_options.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.resetFormat()
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
            # Рендер прерывается на ближайшем on_progress; запрос к LLM и загрузку
            # на YouTube (у неё нет отмены) придётся дождаться.
            if hasattr(self._worker, "cancel"):
                self._worker.cancel()
            self._thread.quit()
            self._thread.wait()
        super().closeEvent(event)
