"""Фоновый пайплайн: описание -> JSON -> Spec -> MP4. Запускается в отдельном QThread."""
from PySide6.QtCore import QObject, Signal, Slot

from src.ui.backend import api, llm


class RenderWorker(QObject):
    progress = Signal(str)
    finished = Signal(str)  # путь к готовому MP4
    failed = Signal(str)

    def __init__(self, user_text: str, out_path: str):
        super().__init__()
        self._user_text = user_text
        self._out_path = out_path

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Генерация сцен…")
            raw = llm.generate_spec(self._user_text)
            spec = api.parse_spec(raw)
            self.progress.emit("Рендер видео…")
            path = api.render_video(spec, self._out_path)
        except api.SpecError as e:
            self.failed.emit(f"Ошибка спецификации: {e}")
        except Exception as e:  # окно не должно падать из-за backend
            self.failed.emit(f"Ошибка: {e}")
        else:
            self.finished.emit(path)
