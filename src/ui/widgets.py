"""Виджеты окна: знак продукта, переключатель 2D/3D, превью 9:16, сценарий и лента сцен."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from src.ui.theme import T, font

SCENE_NAMES = {"text": "Текст", "image": "Картинка", "chart": "График", "say": "Реплика"}
WHO_NAMES = {"robot": "Робот", "girl": "Девушка"}
SHOT_NAMES = {"wide": "общий план", "medium": "средний план", "close": "крупный план"}


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def scene_summary(scene: dict) -> str:
    kind = scene.get("type")
    if kind == "text":
        return scene.get("text", "")
    if kind == "image":
        return scene.get("path", "")
    if kind == "chart":
        return f"{len(scene.get('data', []))} точки на графике"
    if kind == "say":
        who = WHO_NAMES.get(scene.get("who"), scene.get("who", ""))
        return f"{who}: «{scene.get('text', '')}»"
    return ""


def scene_at(scenes: list, position: float):
    return next((s for s in scenes if s["start"] <= position < s["end"]), None)


def _draw_mark(p: QPainter, rect: QRectF, color: QColor, stroke: float) -> None:
    """Вертикальный кадр 9:16 с кнопкой воспроизведения — то, что делает продукт."""
    h = rect.height()
    w = h * 9 / 16
    frame = QRectF(rect.center().x() - w / 2, rect.top(), w, h).adjusted(stroke / 2, stroke / 2, -stroke / 2, -stroke / 2)
    p.setPen(QPen(color, stroke))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(frame, w * 0.18, w * 0.18)
    c, s = frame.center(), w * 0.2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPolygon(QPolygonF([QPointF(c.x() - s * 0.7, c.y() - s), QPointF(c.x() - s * 0.7, c.y() + s),
                             QPointF(c.x() + s, c.y())]))


def mark_icon(size: int = 64) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_mark(p, QRectF(0, 0, size, size), QColor(T["accent"]), size / 14)
    p.end()
    return QIcon(pix)


def media_icon(kind: str, color: str = T["text"]) -> QIcon:
    pix = QPixmap(40, 40)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    if kind == "play":
        p.drawPolygon(QPolygonF([QPointF(7.5, 5.5), QPointF(7.5, 14.5), QPointF(15, 10)]))
    else:
        p.drawRoundedRect(QRectF(6, 5.5, 3, 9), 1, 1)
        p.drawRoundedRect(QRectF(11, 5.5, 3, 9), 1, 1)
    p.end()
    return QIcon(pix)


class Mark(QWidget):
    def __init__(self, size: int = 28, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw_mark(p, QRectF(self.rect()), QColor(T["accent"]), 2)


class ModeSwitch(QWidget):
    """Сегментированный переключатель режима: две плитки на сером треке, выбранная — белая."""

    changed = Signal(str)
    MODES = (("2d", "2D", "Текст, картинки, графики"), ("3d", "3D", "Студия и персонажи"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = 0
        self.setFixedHeight(64)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Режим рендера")
        self._update_tooltip()

    def value(self) -> str:
        return self.MODES[self._index][0]

    def set_value(self, mode: str) -> None:
        index = next(i for i, m in enumerate(self.MODES) if m[0] == mode)
        if index != self._index:
            self._index = index
            self._update_tooltip()
            self.update()
            self.changed.emit(mode)

    def _update_tooltip(self) -> None:
        self.setAccessibleDescription(f"Выбран режим {self.MODES[self._index][1]}")

    def _segment(self, i: int) -> QRectF:
        inner = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        w = inner.width() / 2
        return QRectF(inner.left() + i * w, inner.top(), w, inner.height())

    def mousePressEvent(self, event) -> None:
        if self.isEnabled():
            self.set_value(self.MODES[0 if event.position().x() < self.width() / 2 else 1][0])

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Space):
            self.set_value(self.MODES[1 - self._index][0])
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(T["text"]), 1) if self.hasFocus() else Qt.PenStyle.NoPen)
        p.setBrush(QColor(T["raised"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        for i, (_, title, note) in enumerate(self.MODES):
            seg = self._segment(i)
            selected = i == self._index
            if selected:
                p.setPen(QPen(QColor(T["border"]), 1))
                p.setBrush(QColor(T["sheet"]))
                p.drawRoundedRect(seg.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            enabled = self.isEnabled()
            p.setPen(QColor(T["text"] if selected and enabled else T["muted"]))
            p.setFont(font("body", QFont.Weight.DemiBold))
            p.drawText(seg.adjusted(14, 10, -10, -28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, title)
            p.setPen(QColor(T["muted"]))
            p.setFont(font("small"))
            fm = QFontMetrics(p.font())
            p.drawText(seg.adjusted(14, 32, -10, -8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       fm.elidedText(note, Qt.TextElideMode.ElideRight, int(seg.width()) - 24))


class PreviewFrame(QWidget):
    """Кадр 9:16. Пусто, идёт работа, постер текущей сцены или настоящее видео (QVideoWidget)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 300)
        self._state = "empty"
        self._stage = ""
        self._percent = None
        self._scene = None
        self.video = QVideoWidget(self)
        self.video.hide()

    def frame_rect(self) -> QRectF:
        # Прижат к левому верхнему углу: ширину виджету задаёт окно, пустых полос по бокам нет.
        h = float(self.height())
        w = h * 9 / 16
        if w > self.width():
            w = float(self.width())
            h = w * 16 / 9
        return QRectF(0, 0, w, h)

    def resizeEvent(self, event) -> None:
        self.video.setGeometry(self.frame_rect().toRect())

    def show_empty(self) -> None:
        self._state, self._scene = "empty", None
        self.video.hide()
        self.update()

    def show_working(self, stage: str, percent=None) -> None:
        self._state, self._stage, self._percent = "working", stage, percent
        self.video.hide()
        self.update()

    def show_poster(self, scene) -> None:
        self._state, self._scene = "poster", scene
        self.video.hide()
        self.update()

    def show_video(self) -> None:
        self._state = "video"
        self.video.setGeometry(self.frame_rect().toRect())
        self.video.show()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.frame_rect()
        dark = self._state in ("poster", "video")
        p.setPen(Qt.PenStyle.NoPen if dark else QPen(QColor(T["border"]), 1))
        p.setBrush(QColor("#111315" if dark else T["raised"]))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self._state == "empty":
            _draw_mark(p, QRectF(r.center().x() - 14, r.center().y() - 52, 28, 28), QColor(T["control"]), 2)
            self._text(p, QRectF(r.left(), r.center().y() - 10, r.width(), 22), "Здесь появится ролик",
                       font("body", QFont.Weight.Medium), T["text"])
            self._text(p, QRectF(r.left(), r.center().y() + 14, r.width(), 18), "1080 × 1920 · MP4",
                       font("small"), T["muted"])
        elif self._state == "working":
            if self._percent is not None:
                self._text(p, QRectF(r.left(), r.center().y() - 34, r.width(), 32), f"{self._percent}%",
                           font("title", QFont.Weight.DemiBold), T["text"])
            self._text(p, QRectF(r.left(), r.center().y() + 4, r.width(), 22), self._stage,
                       font("body", QFont.Weight.Medium), T["muted"])
        elif self._state == "poster" and self._scene:
            self._poster(p, r, self._scene)

    @staticmethod
    def _text(p, rect, text, f, color, flags=Qt.AlignmentFlag.AlignCenter) -> None:
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(rect, flags | Qt.TextFlag.TextWordWrap, text)

    def _poster(self, p: QPainter, r: QRectF, scene: dict) -> None:
        """Набросок кадра из самой сцены: так демо показывает ролик без настоящего видео."""
        pad = r.width() * 0.1
        body = r.adjusted(pad, pad * 2, -pad, -pad * 2)
        kind = scene.get("type")
        title = QFont(font("title", QFont.Weight.DemiBold))
        title.setPixelSize(max(14, int(r.width() / 13)))
        if kind == "chart" and scene.get("data"):
            data = scene["data"]
            top = max(y for _, y in data) or 1
            bw = body.width() / (len(data) * 1.6)
            for i, (_, y) in enumerate(data):
                h = body.height() * 0.6 * y / top
                x = body.left() + i * bw * 1.6 + bw * 0.3
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#5fb3c6") if i == len(data) - 1 else QColor("#3a3f44"))
                p.drawRoundedRect(QRectF(x, body.bottom() - h, bw, h), 3, 3)
        else:
            text = scene_summary(scene) or SCENE_NAMES.get(kind, "")
            self._text(p, body, text, title, "#ffffff", Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


class ScriptRow(QFrame):
    def __init__(self, scene: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("ScriptRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        self.time = QLabel(f"{fmt_time(scene['start'])}–{fmt_time(scene['end'])}")
        self.time.setFixedWidth(72)
        self.time.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        kind = QLabel(SCENE_NAMES.get(scene.get("type"), scene.get("type", "")) +
                      (f" · {SHOT_NAMES[scene['shot']]}" if scene.get("shot") in SHOT_NAMES else ""))
        kind.setProperty("role", "muted")
        summary = QLabel(scene_summary(scene))
        summary.setWordWrap(True)
        text_col.addWidget(kind)
        text_col.addWidget(summary)
        layout.addWidget(self.time)
        layout.addLayout(text_col, 1)
        self.set_current(False)

    def set_current(self, current: bool) -> None:
        bg = T["accent_tint"] if current else "transparent"
        color = T["accent"] if current else T["muted"]
        self.setStyleSheet(f"#ScriptRow {{ background: {bg}; border-radius: 8px; }}")
        self.time.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: {600 if current else 400};")


class ScriptList(QWidget):
    """Сценарий от LLM словами: что за сцена, когда, о чём."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._rows = []
        self._scenes = []
        self._current = None
        self.set_scenes([])

    def set_scenes(self, scenes: list) -> None:
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget:  # прячем сразу: deleteLater сработает позже и успел бы дорисоваться
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._scenes, self._rows, self._current = list(scenes), [], None
        if not scenes:
            self._layout.addWidget(self._empty_state())
        for scene in scenes:
            row = ScriptRow(scene)
            self._rows.append(row)
            self._layout.addWidget(row)
        self._layout.addStretch(1)

    @staticmethod
    def _empty_state() -> QFrame:
        box = QFrame(objectName="ScriptEmpty")
        box.setStyleSheet(f"#ScriptEmpty {{ border: 1px dashed {T['control']}; border-radius: 8px; }}")
        col = QVBoxLayout(box)
        col.setContentsMargins(16, 14, 16, 16)
        col.setSpacing(10)
        lead = QLabel("Здесь появится сценарий: какие сцены, в каком порядке и сколько длится каждая.")
        lead.setWordWrap(True)
        col.addWidget(lead)
        for tip in ("Длительность: от 5 до 60 секунд.",
                    "Цифры из описания станут графиком.",
                    "Для персонажей и реплик выберите 3D."):
            label = QLabel(tip)
            label.setWordWrap(True)
            label.setProperty("role", "muted")
            col.addWidget(label)
        return box

    def set_position(self, seconds: float) -> None:
        current = scene_at(self._scenes, seconds)
        index = self._scenes.index(current) if current else None
        if index != self._current:
            if self._current is not None:
                self._rows[self._current].set_current(False)
            if index is not None:
                self._rows[index].set_current(True)
            self._current = index


class SceneTimeline(QWidget):
    """Лента сцен во времени. Во время рендера заливается по готовым кадрам, потом — бегунок.

    Единственное место, где окно позволяет себе цвет.
    """

    seek_requested = Signal(float)
    TRACK = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.TRACK + 22)
        self._scenes, self._duration, self._position = [], 0.0, 0.0
        self._progress = None  # доля готовых кадров во время рендера, иначе None

    def set_scenes(self, scenes: list, duration: float) -> None:
        self._scenes, self._duration, self._position = list(scenes), float(duration), 0.0
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        self.update()

    def set_progress(self, fraction) -> None:
        self._progress = fraction
        self.setCursor(Qt.CursorShape.ArrowCursor if fraction is not None else Qt.CursorShape.PointingHandCursor)
        self.update()

    def _x(self, seconds: float) -> float:
        return self.width() * seconds / self._duration if self._duration else 0

    def mousePressEvent(self, event) -> None:
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._duration and self._progress is None and event.buttons() & Qt.MouseButton.LeftButton:
            x = min(max(event.position().x(), 0), self.width())
            self.seek_requested.emit(self._duration * x / self.width())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 0, self.width(), self.TRACK)
        if not self._scenes:
            p.setPen(QPen(QColor(T["control"]), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(QColor(T["muted"]))
            p.setFont(font("small"))
            p.drawText(track, Qt.AlignmentFlag.AlignCenter, "Лента сцен появится после генерации")
            return
        rendering = self._progress is not None
        current = None if rendering else scene_at(self._scenes, self._position)
        edge = self.width() * self._progress if rendering else self._x(self._position)
        fm_font = font("small", QFont.Weight.Medium)
        p.setFont(fm_font)
        fm = QFontMetrics(fm_font)
        for scene in self._scenes:
            seg = QRectF(self._x(scene["start"]) + 1, 0, self._x(scene["end"]) - self._x(scene["start"]) - 2, self.TRACK)
            lit = seg.left() < edge if rendering else scene is current
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["active"]))
            p.drawRoundedRect(seg, 6, 6)
            if lit:
                p.save()
                if rendering:  # заливка только до последнего готового кадра
                    p.setClipRect(QRectF(seg.left(), 0, max(0.0, edge - seg.left()), self.TRACK))
                p.setBrush(QColor(T["accent_tint"]))
                p.drawRoundedRect(seg, 6, 6)
                p.restore()
            label = fm.elidedText(SCENE_NAMES.get(scene["type"], ""), Qt.TextElideMode.ElideRight, int(seg.width()) - 16)
            p.setPen(QColor(T["accent"] if lit else T["muted"]))
            p.drawText(seg.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        # бегунок или граница готовых кадров
        p.setPen(QPen(QColor(T["accent"]), 2))
        p.drawLine(QPointF(edge, -1), QPointF(edge, self.TRACK + 1))
        # подписи времени
        step = 5 if self._duration <= 30 else 10
        p.setFont(font("small"))
        p.setPen(QColor(T["muted"]))
        t = 0
        while t <= self._duration + 0.01:
            tx = self._x(t)
            align = Qt.AlignmentFlag.AlignLeft if t == 0 else (
                Qt.AlignmentFlag.AlignRight if t >= self._duration - 0.01 else Qt.AlignmentFlag.AlignHCenter)
            box = QRectF(tx - (0 if t == 0 else 40 if align == Qt.AlignmentFlag.AlignRight else 20),
                         self.TRACK + 4, 40, 16)
            p.drawText(box, align | Qt.AlignmentFlag.AlignTop, fmt_time(t))
            t += step


class StatusPill(QLabel):
    STYLES = {
        "neutral": (T["active"], T["muted"]),
        "working": (T["accent_tint"], T["accent"]),
        "positive": (T["positive_tint"], T["positive"]),
        "negative": (T["negative_tint"], T["negative"]),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.set_state("neutral", "Черновик")

    def set_state(self, kind: str, text: str) -> None:
        bg, fg = self.STYLES[kind]
        self.setText(text)
        self.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 11px; padding: 0 10px;"
                           f" font-size: 12px; font-weight: 600;")

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), 22)
