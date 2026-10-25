"""Окно Shorts Studio: дизайн и «коробка». С программой его связывает src/ui/app.py.

Окно ничего не генерирует само. Наружу оно отдаёт сигналы, внутрь принимает состояния:

    window.render_requested(text, mode, options)  # «Создать ролик»; mode: "auto" | "2d" | "3d",
                                                  # options — выбор из features.CHOICES
    window.cancel_requested()             # нажали «Отмена» или Esc
    window.reveal_requested(path)         # нажали «Показать в папке»
    window.publish_requested(path)        # нажали «Опубликовать на YouTube»
    window.about_to_close()               # окно закрывается: остановить рендер

    window.set_generating()                       # LLM пишет сценарий
    window.set_render_mode(mode)                  # режим готового сценария (в «Авто» — выбор модели)
    window.set_rendering(done, total, scenes=..., duration=...)  # кадры из on_progress
    window.set_done(video_path, scenes, duration)  # готово; video_path=None — постер из сцен
    window.set_cancelled() / window.set_error(text) / window.set_idle()
    window.set_warning(text)                      # видео есть, но что-то не удалось (озвучка)
    window.show_extra(title, text, ok)            # карточка доп. результата (features.EXTRAS)
    window.set_publishing(sent, total) / set_published(url) / set_publish_failed(text)
"""
import os

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.ui.features import CHOICES
from src.ui.widgets import (
    ModeSwitch, PreviewFrame, SceneTimeline, ScriptList, StatusPill, fmt_time, mark_icon, media_icon, scene_at,
)

MAX_CHARS = 2000
_BROWSE = "__browse__"  # служебное значение пункта «Свой файл…»
MODE_NOTES = {
    "auto": "2D или 3D Claude выберет по описанию. Напишите «3D», чтобы снять студию с героями.",
    "2d": "1080 × 1920, 60 кадров/с. Готово за секунды.",
    "3d": "1080 × 1920, 30 кадров/с. Рендер занимает несколько минут.",
}


def advanced_label(choices: list, expanded: bool) -> str:
    """Текст кнопки «Дополнительно»: выбранное видно, даже когда блок свёрнут."""
    text = "Дополнительно" + (f": {', '.join(choices)}" if choices else "")
    return f"{text}  {'▾' if expanded else '▸'}"


def _label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    return label


class _Body(QWidget):
    """Ряд «превью + сценарий»: превью всегда шириной ровно под 9:16 от доступной высоты."""

    preview = None

    def resizeEvent(self, event) -> None:
        if self.preview is not None:
            self.preview.setFixedWidth(max(200, min(int(self.height() * 9 / 16), int(self.width() * 0.6))))
        super().resizeEvent(event)


class ExtraCard(QFrame):
    """Дополнительный результат под сценарием: заголовок, текст и «Копировать»."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ExtraCard")
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 10, 14)
        col.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_label(title, "label"), 1)
        self.copy_button = QPushButton("Копировать", objectName="Quiet")
        self.copy_button.clicked.connect(self._copy)
        head.addWidget(self.copy_button)
        col.addLayout(head)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.text)

    def set_content(self, text: str, ok: bool) -> None:
        self.text.setText(text)
        self.text.setProperty("role", "" if ok else "muted")
        self.text.style().polish(self.text)
        self.copy_button.setVisible(ok)
        self.copy_button.setText("Копировать")

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text.text())
        self.copy_button.setText("Скопировано")


class ShellWindow(QMainWindow):
    render_requested = Signal(str, str, dict)
    cancel_requested = Signal()
    reveal_requested = Signal(str)
    publish_requested = Signal(str)  # путь к готовому MP4
    about_to_close = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shorts Studio")
        self.setWindowIcon(mark_icon())
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)
        self._scenes, self._duration, self._video_path = [], 0.0, None
        self._position = 0.0
        self._render_mode = None  # режим готового сценария; в «Авто» его выбирает модель

        root = QWidget(objectName="Frame")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 8, 8, 8)
        layout.setSpacing(0)
        layout.addWidget(self._build_panel())
        layout.addWidget(self._build_sheet(), 1)
        self.setCentralWidget(root)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.preview.video)
        self.player.positionChanged.connect(lambda ms: self._set_position(ms / 1000))
        self.player.playbackStateChanged.connect(self._sync_play_icon)
        self._clock = QTimer(self, interval=40)  # проигрывание постера, когда видео нет
        self._clock.timeout.connect(self._tick)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._request_render)
        QShortcut(QKeySequence("Escape"), self, activated=self._request_cancel)
        self.set_idle()

    # ---------- раскладка ----------

    def _build_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(392)
        col = QVBoxLayout(panel)
        col.setContentsMargins(24, 22, 24, 16)  # заголовок на одной высоте с «Превью» на листе
        col.setSpacing(0)

        col.addWidget(_label("Новый ролик", "title"))
        col.addSpacing(20)
        col.addWidget(_label("Описание ролика", "label"))
        col.addSpacing(8)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(
            "Например: ролик на 30 секунд о том, как кофе влияет на сон. "
            "Три факта, график по часам и вывод в конце.")
        self.input.setAccessibleName("Описание ролика")
        self.input.textChanged.connect(self._on_text_changed)
        col.addWidget(self.input, 1)
        col.addSpacing(6)
        helper = QHBoxLayout()
        helper.addWidget(_label("Тема, факты и цифры. Сцены соберутся сами.", "muted"), 1)
        self.counter = _label(f"0 / {MAX_CHARS}", "muted")
        helper.addWidget(self.counter)
        col.addLayout(helper)
        col.addSpacing(16)

        # Ролик делается по одному описанию. Режим и настройки из features.CHOICES лежат
        # в свёрнутом блоке «Дополнительно»; выбранное там видно на самой кнопке.
        self.advanced_button = QPushButton(objectName="Quiet")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setStyleSheet("text-align: left; padding-left: 0;")
        self.advanced_button.setCursor(Qt.CursorShape.PointingHandCursor)
        col.addWidget(self.advanced_button)
        self.advanced = QWidget()
        adv = QVBoxLayout(self.advanced)
        adv.setContentsMargins(0, 12, 0, 0)
        adv.setSpacing(0)

        adv.addWidget(_label("Режим", "label"))
        adv.addSpacing(8)
        self.mode = ModeSwitch()
        self.mode.changed.connect(self._on_mode_changed)
        adv.addWidget(self.mode)
        adv.addSpacing(8)
        self.mode_note = _label(MODE_NOTES["auto"], "muted")
        self.mode_note.setWordWrap(True)
        adv.addWidget(self.mode_note)

        self._choices = {}  # настройки из features.CHOICES рисуются сами
        self._choice_rows, self._choice_modes = {}, {}
        for choice in CHOICES:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 12, 0, 0)
            label = _label(choice.label, "label")
            label.setFixedWidth(90)
            row_layout.addWidget(label)
            box = QComboBox()
            box.setAccessibleName(choice.label)
            box.setToolTip(choice.hint)
            for value, text in choice.resolve():
                box.addItem(text, value)
            if choice.browse:
                box.addItem("Свой файл…", _BROWSE)
                box.activated.connect(lambda index, b=box, c=choice: self._browse(b, c, index))
            box.currentIndexChanged.connect(self._update_advanced)
            row_layout.addWidget(box, 1)
            adv.addWidget(row)
            self._choices[choice.key] = box
            self._choice_rows[choice.key] = row
            self._choice_modes[choice.key] = choice.mode
        self._sync_choices()
        col.addWidget(self.advanced)
        self.advanced_button.toggled.connect(self._update_advanced)
        self._update_advanced()
        col.addSpacing(24)

        self.progress_box = QWidget()
        pcol = QVBoxLayout(self.progress_box)
        pcol.setContentsMargins(0, 0, 0, 16)
        pcol.setSpacing(8)
        prow = QHBoxLayout()
        self.stage = _label("", "label")
        self.stage_detail = _label("", "muted")
        prow.addWidget(self.stage, 1)
        prow.addWidget(self.stage_detail)
        pcol.addLayout(prow)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        pcol.addWidget(self.progress)
        col.addWidget(self.progress_box)

        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setOpenExternalLinks(True)  # ссылка на опубликованный ролик
        self.notice.setContentsMargins(0, 0, 0, 12)
        col.addWidget(self.notice)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.create_button = QPushButton("Создать ролик", objectName="Primary")
        self.create_button.setToolTip("Ctrl+Enter")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.clicked.connect(self._request_render)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setToolTip("Esc")
        self.cancel_button.clicked.connect(self._request_cancel)
        buttons.addWidget(self.create_button, 1)
        buttons.addWidget(self.cancel_button)
        col.addLayout(buttons)
        return panel

    def _build_sheet(self) -> QWidget:
        sheet = QFrame(objectName="Sheet")
        col = QVBoxLayout(sheet)
        col.setContentsMargins(24, 20, 24, 20)
        col.setSpacing(0)

        header_box = QWidget()
        header_box.setFixedHeight(32)  # «Показать в папке» появляется, не сдвигая превью
        header = QHBoxLayout(header_box)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(_label("Превью", "section"))
        self.pill = StatusPill()
        header.addWidget(self.pill)
        header.addStretch(1)
        self.reveal_button = QPushButton("Показать в папке", objectName="Quiet")
        self.reveal_button.clicked.connect(lambda: self.reveal_requested.emit(self._video_path or ""))
        header.addWidget(self.reveal_button)
        self.publish_button = QPushButton("Опубликовать на YouTube", objectName="Quiet")
        self.publish_button.setToolTip(
            "Нужен OAuth-клиент Desktop app из Google Cloud: ~/.shortsstudio/client_secret.json "
            "или путь в WIBECODE_YT_CLIENT_SECRET. Пока проект не прошёл аудит Google, "
            "YouTube публикует ролик как приватный.")
        self.publish_button.clicked.connect(lambda: self.publish_requested.emit(self._video_path or ""))
        header.addWidget(self.publish_button)
        col.addWidget(header_box)
        col.addSpacing(16)

        body_box = _Body()
        body = QHBoxLayout(body_box)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(24)
        self.preview = PreviewFrame()
        body_box.preview = self.preview
        body.addWidget(self.preview)
        script_col = QVBoxLayout()
        script_col.setSpacing(4)
        script_head = QHBoxLayout()
        script_head.addWidget(_label("Сценарий", "label"))
        script_head.addStretch(1)
        self.script_meta = _label("", "muted")
        script_head.addWidget(self.script_meta)
        script_col.addLayout(script_head)
        script_col.addSpacing(6)
        self.script = ScriptList()
        self._extras = {}  # заголовок -> ExtraCard
        self.extras_box = QVBoxLayout()
        self.extras_box.setContentsMargins(0, 16, 0, 0)
        self.extras_box.setSpacing(12)
        script_area = QWidget()
        area_col = QVBoxLayout(script_area)
        area_col.setContentsMargins(0, 0, 0, 0)
        area_col.setSpacing(0)
        area_col.addWidget(self.script)
        area_col.addLayout(self.extras_box)
        area_col.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(script_area)
        script_col.addWidget(scroll, 1)
        script_box = QWidget()
        script_box.setLayout(script_col)
        script_box.setMinimumWidth(260)
        body.addWidget(script_box, 1)
        col.addWidget(body_box, 1)
        col.addSpacing(20)

        self.timeline = SceneTimeline()
        self.timeline.seek_requested.connect(self._seek)
        col.addWidget(self.timeline)
        col.addSpacing(10)

        transport = QHBoxLayout()
        transport.setSpacing(12)
        self.play_button = QPushButton(objectName="Icon")
        self.play_button.setIcon(media_icon("play"))
        self.play_button.setAccessibleName("Воспроизвести")
        self.play_button.clicked.connect(self._toggle_play)
        transport.addWidget(self.play_button)
        self.time_label = _label("0:00 / 0:00", "muted")
        transport.addWidget(self.time_label)
        transport.addStretch(1)
        self.format_label = _label("", "muted")
        transport.addWidget(self.format_label)
        col.addLayout(transport)
        return sheet

    # ---------- состояния (их вызывает программа) ----------

    def set_idle(self) -> None:
        self._set_busy(False)
        self._show_notice("")
        self.pill.set_state("neutral", "Черновик")
        self._clear_result()

    def set_generating(self) -> None:
        self._set_busy(True)
        self._show_notice("")
        self.pill.set_state("working", "Генерация")
        self._render_mode = None
        self._clear_result()
        self.stage.setText("Пишем сценарий")
        self.stage_detail.setText("")
        self.progress.setRange(0, 0)
        self.preview.show_working("Пишем сценарий…")

    @Slot(str)
    def set_stage(self, text: str) -> None:
        """Текст текущего этапа; кадры и блокировка настроек остаются у своих обработчиков."""
        self.stage.setText(text)
        self.preview.show_working(text)

    def set_rendering(self, done: int, total: int, scenes=None, duration=None) -> None:
        self._set_busy(True)
        if scenes is not None and scenes != self._scenes:
            self._set_scenes(scenes, duration)
        self.pill.set_state("working", "Рендер")
        if total <= 0:
            self.progress.setRange(0, 0)
            self.stage.setText("Рендерим видео")
            self.stage_detail.setText("")
            self.preview.show_working("Рендерим кадры…")
            return
        assembling = total > 1 and done == total - 1
        percent = round(100 * done / total)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.timeline.set_progress(done / total)
        self.stage.setText("Собираем MP4" if assembling else "Рендерим видео")
        self.stage_detail.setText(f"кадр {done} из {total} · {percent}%")
        self.preview.show_working("Собираем MP4…" if assembling else "Рендерим кадры…", percent)

    def set_done(self, video_path, scenes: list, duration: float) -> None:
        self._set_busy(False)
        self._show_notice("")
        self.pill.set_state("positive", "Готово")
        self._set_scenes(scenes, duration)
        self._video_path = video_path if video_path and os.path.exists(video_path) else None
        self.reveal_button.setVisible(self._video_path is not None)
        self.publish_button.setVisible(self._video_path is not None)
        self.play_button.setEnabled(True)
        if self._video_path:
            self.preview.show_video()
            self.player.setSource(QUrl.fromLocalFile(self._video_path))
            self.player.play()
        else:
            self.preview.show_poster(self._scenes[0] if self._scenes else None)
            self._set_position(0)

    def set_cancelled(self) -> None:
        self._set_busy(False)
        self.pill.set_state("neutral", "Отменено")
        self._show_notice("Рендер отменён. Описание осталось, можно поправить и запустить снова.", "muted")
        self._clear_result()

    def set_error(self, message: str) -> None:
        self._set_busy(False)
        self.pill.set_state("negative", "Ошибка")
        self._show_notice(message, "error")
        self._clear_result()

    def set_warning(self, message: str) -> None:
        """После set_done: видео готово, но часть работы не удалась (например, озвучка)."""
        self._show_notice(message, "error")

    def set_publishing(self, sent: int = 0, total: int = 0) -> None:
        """Загрузка на YouTube: видео остаётся в превью, отмены у загрузки нет."""
        self._set_busy(True)
        self.cancel_button.setVisible(False)
        self.publish_button.setEnabled(False)
        self._show_notice("")
        self.pill.set_state("working", "Публикация")
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(sent)
            self.stage.setText("Загрузка на YouTube")
            self.stage_detail.setText(f"{round(100 * sent / total)}%")
        else:
            self.progress.setRange(0, 0)
            self.stage.setText("Вход в Google")
            self.stage_detail.setText("при первом запуске откроется браузер")

    def set_published(self, url: str) -> None:
        self._set_busy(False)
        self.publish_button.setEnabled(True)
        self.pill.set_state("positive", "Опубликовано")
        self._show_notice(f'Ролик на YouTube: <a href="{url}">{url}</a>', "muted")

    def set_publish_failed(self, message: str) -> None:
        self._set_busy(False)
        self.publish_button.setEnabled(True)
        self.pill.set_state("positive", "Готово")
        self._show_notice(message, "error")

    def show_extra(self, title: str, text: str, ok: bool = True) -> None:
        card = self._extras.get(title)
        if card is None:
            card = self._extras[title] = ExtraCard(title)
            self.extras_box.addWidget(card)
        card.set_content(text, ok)

    def options(self) -> dict:
        return {key: box.currentData() for key, box in self._choices.items()
                if not self._choice_modes[key] or self._choice_modes[key] == self.mode.value()}

    def _sync_choices(self) -> None:
        for key, row in self._choice_rows.items():
            row.setVisible(not self._choice_modes[key] or self._choice_modes[key] == self.mode.value())

    def _browse(self, box: QComboBox, choice, index: int) -> None:
        """Пункт «Свой файл…»: выбранный файл становится вариантом списка, отмена — откат."""
        if box.itemData(index) != _BROWSE:
            box.setProperty("last_index", index)
            return
        path, _ = QFileDialog.getOpenFileName(self, choice.label, "", choice.browse)
        if path:
            box.insertItem(index, os.path.basename(path), path)
            box.setCurrentIndex(index)
            box.setProperty("last_index", index)
        else:
            box.setCurrentIndex(box.property("last_index") or 0)

    # ---------- внутреннее ----------

    def _set_busy(self, busy: bool) -> None:
        self.input.setReadOnly(busy)
        self.mode.setEnabled(not busy)
        for box in self._choices.values():
            box.setEnabled(not busy)
        self.create_button.setEnabled(not busy and bool(self.input.toPlainText().strip()))
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.progress_box.setVisible(busy)

    def _show_notice(self, text: str, role: str = "muted") -> None:
        self.notice.setProperty("role", role)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _clear_result(self) -> None:
        self._stop_playback()
        self.player.setSource(QUrl())
        self._video_path = None
        self.reveal_button.setVisible(False)
        self.publish_button.setVisible(False)
        self.publish_button.setEnabled(True)
        self.play_button.setEnabled(False)
        self._set_scenes([], 0)
        self.preview.show_empty()
        for card in self._extras.values():
            card.hide()
            card.setParent(None)
            card.deleteLater()
        self._extras.clear()

    def _set_scenes(self, scenes: list, duration) -> None:
        self.timeline.set_progress(None)
        self._scenes = list(scenes)
        self._duration = float(duration or (max((s["end"] for s in scenes), default=0)))
        self.script.set_scenes(self._scenes)
        self.timeline.set_scenes(self._scenes, self._duration)
        count = len(self._scenes)
        noun = "сцена" if count % 10 == 1 and count % 100 != 11 else (
            "сцены" if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14 else "сцен")
        self.script_meta.setText(f"{count} {noun} · {fmt_time(self._duration)}" if count else "")
        mode = self._render_mode or self.mode.value()
        fps = "30" if any(s.get("type") == "say" for s in self._scenes) or mode == "3d" else "60"
        self.format_label.setText(f"1080 × 1920 · {fps} кадров/с" if count else "")
        self._position = 0.0
        self._update_time()

    def _set_position(self, seconds: float) -> None:
        self._position = min(seconds, self._duration)
        self.timeline.set_position(self._position)
        self.script.set_position(self._position)
        if self.preview._state in ("poster", "empty") and self._scenes and not self._video_path:
            self.preview.show_poster(scene_at(self._scenes, self._position) or self._scenes[-1])
        self._update_time()

    def _update_time(self) -> None:
        self.time_label.setText(f"{fmt_time(self._position)} / {fmt_time(self._duration)}")

    @Slot(float)
    def _seek(self, seconds: float) -> None:
        if self._video_path:
            self.player.setPosition(int(seconds * 1000))
        else:
            self._set_position(seconds)

    def _toggle_play(self) -> None:
        if self._video_path:
            playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            self.player.pause() if playing else self.player.play()
            return
        if self._clock.isActive():
            self._stop_playback()
        else:
            if self._position >= self._duration:
                self._set_position(0)
            self._clock.start()
            self.play_button.setIcon(media_icon("pause"))

    def _tick(self) -> None:
        self._set_position(self._position + self._clock.interval() / 1000)
        if self._position >= self._duration:
            self._stop_playback()

    def _stop_playback(self) -> None:
        self._clock.stop()
        self.player.pause()
        self.play_button.setIcon(media_icon("play"))

    def _sync_play_icon(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setIcon(media_icon("pause" if playing else "play"))

    def _on_text_changed(self) -> None:
        text = self.input.toPlainText()
        if len(text) > MAX_CHARS:
            cursor = self.input.textCursor()
            self.input.setPlainText(text[:MAX_CHARS])
            cursor.setPosition(MAX_CHARS)
            self.input.setTextCursor(cursor)
            return
        self.counter.setText(f"{len(text)} / {MAX_CHARS}")
        if not self.cancel_button.isVisible():
            self.create_button.setEnabled(bool(text.strip()))

    def set_render_mode(self, mode: str) -> None:
        """Режим готового сценария: в «Авто» его выбрала модель, от него зависят кадры/с."""
        self._render_mode = mode

    def _on_mode_changed(self, mode: str) -> None:
        self.mode_note.setText(MODE_NOTES[mode])
        self._sync_choices()
        self._update_advanced()

    def _update_advanced(self, *_) -> None:
        expanded = self.advanced_button.isChecked()
        self.advanced.setVisible(expanded)
        mode = self.mode.value()
        chosen = [title for value, title, _ in ModeSwitch.MODES if value == mode and value != "auto"]
        active = self.options()
        chosen += [box.currentText() for key, box in self._choices.items()
                   if key in active and box.currentIndex() > 0]
        self.advanced_button.setText(advanced_label(chosen, expanded))

    def _request_render(self) -> None:
        text = self.input.toPlainText().strip()
        if text and self.create_button.isEnabled():
            self.render_requested.emit(text, self.mode.value(), self.options())

    def _request_cancel(self) -> None:
        if self.cancel_button.isVisible() and self.cancel_button.isEnabled():
            self.cancel_button.setEnabled(False)
            self.stage.setText("Отменяем…")
            self.cancel_requested.emit()

    def closeEvent(self, event) -> None:
        self._stop_playback()
        self.about_to_close.emit()  # связка успевает остановить рендер, пока окно ещё живо
        super().closeEvent(event)
