"""Демо окна без backend: python -m src.ui.shell_demo

Таймеры изображают программу: сценарий, рендер с прогрессом, готовый ролик (постер из сцен).
В описании слово «ошибка» показывает состояние ошибки; «Отмена» и Esc работают.
"""
import sys

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from src.ui.shell import ShellWindow
from src.ui.theme import apply_theme


def sample_scenes(text: str, mode: str) -> tuple[list, float]:
    title = text.split(".")[0].strip()[:70] or "Ролик"
    if mode == "3d":
        return [
            {"type": "text", "text": title, "start": 0, "end": 3},
            {"type": "say", "who": "robot", "shot": "medium", "text": "Сейчас покажу главное.", "start": 3, "end": 7},
            {"type": "chart", "data": [[1, 2], [2, 3], [3, 5]], "start": 7, "end": 11},
            {"type": "say", "who": "girl", "shot": "close", "text": "Коротко и по делу.", "start": 11, "end": 15},
        ], 15.0
    return [
        {"type": "text", "text": title, "start": 0, "end": 4},
        {"type": "text", "text": "Три факта за 15 секунд", "start": 4, "end": 7},
        {"type": "chart", "data": [[1, 2], [2, 4], [3, 3], [4, 6]], "start": 7, "end": 12},
        {"type": "text", "text": "Вывод в одной фразе", "start": 12, "end": 15},
    ], 15.0


class DemoDriver(QObject):
    def __init__(self, window: ShellWindow):
        super().__init__(window)
        self.w = window
        self._run = 0  # номер запуска: отложенные вызовы от отменённого запуска игнорируются
        self._timer = QTimer(self, interval=50)
        self._timer.timeout.connect(self._step)
        window.render_requested.connect(self.start)
        window.cancel_requested.connect(self.cancel)

    def _later(self, ms: int, callback) -> None:
        run = self._run
        QTimer.singleShot(ms, self, lambda: callback() if run == self._run else None)

    def start(self, text: str, mode: str) -> None:
        self._run += 1
        self._text, self._mode = text, mode
        self.w.set_generating()
        self._later(1400, self._after_llm)

    def _after_llm(self) -> None:
        if "ошибк" in self._text.lower():
            self.w.set_error("Модель не смогла вернуть корректный JSON за 3 попытки. Последняя ошибка: "
                             "scenes[1]: end (18) больше duration (15). Переформулируйте описание.")
            return
        self._scenes, self._duration = sample_scenes(self._text, self._mode)
        self._total = int(self._duration * (30 if self._mode == "3d" else 60))
        self._done = 0
        self.w.set_rendering(0, self._total, self._scenes, self._duration)
        self._timer.start()

    def _step(self) -> None:
        self._done = min(self._done + self._total // 50, self._total - 1)
        self.w.set_rendering(self._done, self._total)
        if self._done == self._total - 1:  # как у настоящего рендера: сборка MP4 на total - 1
            self._timer.stop()
            self._later(700, self._finish)

    def _finish(self) -> None:
        self.w.set_rendering(self._total, self._total)
        self.w.set_done(None, self._scenes, self._duration)

    def cancel(self) -> None:
        self._run += 1
        self._timer.stop()
        QTimer.singleShot(300, self.w.set_cancelled)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = ShellWindow()
    DemoDriver(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
