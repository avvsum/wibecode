"""Дизайн-токены и стили окна (стиль framed-sheet из taste-skill).

Цвет живёт на данных: акцент только на ленте сцен, бегунке и прогрессе. Хром нейтральный,
главная кнопка почти чёрная. Три радиуса: лист 16, поля и кнопки 8, сегменты 6.
"""
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

T = {
    "frame": "#f6f8fa",      # тонированная рамка: левая панель и поля окна
    "sheet": "#ffffff",      # белый лист с работой
    "raised": "#f1f3f5",     # ступень тона внутри листа (рамка превью, трек переключателя)
    "active": "#e7eaed",     # нейтральная заливка сегментов ленты
    "border": "#e6e8eb",     # край листа и карточек
    "rule": "#eef0f2",       # разделители строк
    "control": "#cdd1d5",    # рамка полей ввода
    "text": "#131416",
    "muted": "#5d6064",      # вторичный текст, >= 4.5:1 на рамке и листе
    "faint": "#6b6e72",      # плейсхолдеры, тоже >= 4.5:1
    "primary": "#141517",    # главная кнопка
    "primary_hover": "#2a2c30",
    "accent": "#1b6c80",     # единственный цвет данных
    "accent_tint": "#e3eff2",
    "negative": "#b42318",
    "negative_tint": "#fdecea",
    "positive": "#1e7b4f",
    "positive_tint": "#e3f5ea",
}

FONT_FAMILY = "Segoe UI"
SIZES = {"small": 12, "body": 14, "section": 16, "title": 22}


def font(size: str = "body", weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(SIZES[size])
    f.setWeight(weight)
    return f


QSS = f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: {SIZES['body']}px; color: {T['text']}; }}
QMainWindow, #Frame {{ background: {T['frame']}; }}
#Sheet {{ background: {T['sheet']}; border: 1px solid {T['border']}; border-radius: 16px; }}

QLabel[role="muted"] {{ color: {T['muted']}; font-size: {SIZES['small']}px; }}
QLabel[role="label"] {{ font-weight: 500; font-size: 13px; }}
QLabel[role="title"] {{ font-size: {SIZES['title']}px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: {SIZES['section']}px; font-weight: 600; }}
QLabel[role="error"] {{ color: {T['negative']}; font-size: 13px; }}

QPlainTextEdit {{
    background: {T['sheet']}; border: 1px solid {T['control']}; border-radius: 8px;
    padding: 10px 12px; selection-background-color: {T['accent_tint']}; selection-color: {T['text']};
}}
QPlainTextEdit:focus {{ border: 1px solid {T['text']}; }}
QPlainTextEdit:disabled {{ background: {T['raised']}; color: {T['muted']}; }}

QPushButton {{
    min-height: 40px; border-radius: 8px; padding: 0 16px; font-weight: 600;
    background: {T['sheet']}; border: 1px solid {T['control']};
}}
QPushButton:hover {{ background: {T['raised']}; }}
QPushButton:focus {{ border: 1px solid {T['text']}; }}
QPushButton:disabled {{ color: {T['faint']}; background: {T['raised']}; border-color: {T['border']}; }}
QPushButton#Primary {{ background: {T['primary']}; color: #ffffff; border: none; }}
QPushButton#Primary:hover {{ background: {T['primary_hover']}; }}
QPushButton#Primary:disabled {{ background: {T['active']}; color: {T['muted']}; }}
QPushButton#Quiet {{ min-height: 32px; border: none; background: transparent; color: {T['text']}; padding: 0 8px; }}
QPushButton#Quiet:hover {{ background: {T['raised']}; }}
QPushButton#Icon {{ min-height: 32px; min-width: 32px; max-width: 32px; padding: 0; border-radius: 16px; }}

QComboBox {{
    min-height: 36px; padding: 0 12px; border: 1px solid {T['control']}; border-radius: 8px;
    background: {T['sheet']};
}}
QComboBox:focus {{ border: 1px solid {T['text']}; }}
QComboBox:disabled {{ background: {T['raised']}; color: {T['muted']}; border-color: {T['border']}; }}
QComboBox::drop-down {{ border: none; width: 32px; }}
QComboBox::down-arrow {{ image: url("{{chevron}}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {T['sheet']}; border: 1px solid {T['border']}; padding: 4px; outline: 0;
    selection-background-color: {T['accent_tint']}; selection-color: {T['text']};
}}
QLineEdit {{
    min-height: 36px; padding: 0 12px; border: 1px solid {T['control']}; border-radius: 8px;
    background: {T['sheet']}; selection-background-color: {T['accent_tint']}; selection-color: {T['text']};
}}
QLineEdit:focus {{ border: 1px solid {T['text']}; }}
QLineEdit:disabled {{ background: {T['raised']}; color: {T['muted']}; border-color: {T['border']}; }}
#ExtraCard {{ background: {T['raised']}; border-radius: 8px; }}

QProgressBar {{ background: {T['active']}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {T['accent']}; border-radius: 3px; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {T['control']}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: {T['primary']}; color: #ffffff; border: none; padding: 6px 8px; border-radius: 6px; }}
"""


def _chevron_path() -> str:
    """Стрелка выпадающего списка рисуется кодом в temp: не нужен файл в assets и в сборке."""
    path = Path(tempfile.gettempdir()) / "shorts-studio-chevron.png"
    pix = QPixmap(24, 24)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(T["muted"]), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)])
    p.end()
    pix.save(str(path))
    return path.as_posix()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")  # одинаковая отрисовка на всех ОС, без системных градиентов
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(T["frame"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(T["sheet"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(T["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(T["faint"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(T["accent"]))
    app.setPalette(palette)
    app.setFont(font())
    app.setStyleSheet(QSS.replace("{chevron}", _chevron_path()))
