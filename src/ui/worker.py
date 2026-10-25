"""Фоновый пайплайн: описание -> JSON -> Spec -> MP4. Запускается в отдельном QThread."""
from PySide6.QtCore import QObject, Signal, Slot

from src.ui.backend import api, llm


def with_mode_hint(user_text: str, render_mode: str) -> str:
    """Дописывает выбранный в окне режим подсказкой для LLM.

    По AGENTS.md режим передаётся в user_text до generate_spec; в готовом JSON его не подменяем.
    """
    return f'{user_text}\n\nrender_mode: "{render_mode}"'


class RenderWorker(QObject):
    progress = Signal(str)
    finished = Signal(str)  # путь к готовому MP4
    failed = Signal(str)

    def __init__(self, user_text: str, out_path: str, render_mode: str = "2d"):
        super().__init__()
        self._user_text = user_text
        self._out_path = out_path
        self._render_mode = render_mode

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Генерация сцен…")
            raw = llm.generate_spec(with_mode_hint(self._user_text, self._render_mode))
            spec = api.parse_spec(raw)
            self.progress.emit("Рендер видео…")
            path = api.render_video(spec, self._out_path)
        except api.SpecError as e:
            self.failed.emit(f"Ошибка спецификации: {e}")
        except NotImplementedError as e:
            self.failed.emit(f"Не поддерживается: {e or 'этот режим рендера ещё не реализован'}")
        except Exception as e:  # окно не должно падать из-за backend
            self.failed.emit(f"Ошибка: {e}")
        else:
            self.finished.emit(path)
