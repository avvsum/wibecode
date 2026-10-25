"""Фоновый пайплайн: описание -> JSON -> Spec -> MP4. Запускается в отдельном QThread."""
import json

from PySide6.QtCore import QObject, Signal, Slot

from src.ui.backend import api, llm


def with_render_mode(raw: str, render_mode: str) -> str:
    """Подставляет выбранный в окне render_mode в JSON от LLM, до валидации.

    Битый JSON не трогаем: его отклонит parse_spec с понятной SpecError.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, dict):
        return raw
    data["render_mode"] = render_mode
    return json.dumps(data, ensure_ascii=False)


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
            raw = llm.generate_spec(self._user_text)
            spec = api.parse_spec(with_render_mode(raw, self._render_mode))
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
