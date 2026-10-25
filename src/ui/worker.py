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
    frames = Signal(int, int)  # done, total из on_progress; total == 0 — неизвестно
    finished = Signal(str)  # путь к готовому MP4
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, user_text: str, out_path: str, render_mode: str = "2d"):
        super().__init__()
        self._user_text = user_text
        self._out_path = out_path
        self._render_mode = render_mode
        self._cancel_requested = False

    def cancel(self) -> None:
        """Вызывается из потока окна; рендер прервётся на ближайшем вызове on_progress."""
        self._cancel_requested = True

    def _on_progress(self, done: int, total: int) -> bool:
        self.frames.emit(done, total)
        return not self._cancel_requested

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Генерация сцен…")
            raw = llm.generate_spec(with_mode_hint(self._user_text, self._render_mode))
            spec = api.parse_spec(raw)
            if spec.render_mode != self._render_mode:  # JSON не переписываем, только отказ
                self.failed.emit(
                    f"Модель вернула сценарий для режима {spec.render_mode.upper()}, "
                    f"а выбран {self._render_mode.upper()}. Попробуйте ещё раз или "
                    f"явно укажите в описании, что нужно {self._render_mode.upper()}-видео."
                )
                return
            if self._cancel_requested:  # запрос к LLM не прервать, но рендер уже не начинаем
                raise api.RenderCancelled("отменено до рендера")
            self.progress.emit("Рендер видео…")
            path = api.render_video(spec, self._out_path, on_progress=self._on_progress)
        except api.RenderCancelled:
            self.cancelled.emit()
        except api.ToolNotFoundError as e:  # раньше RenderError и любых OSError
            self.failed.emit(str(e))
        except api.SpecError as e:
            self.failed.emit(f"Ошибка спецификации: {e}")
        except llm.SpecGenerationError as e:
            self.failed.emit(f"{e} Переформулируйте описание.")
        except llm.LLMError as e:
            self.failed.emit(str(e))
        except NotImplementedError as e:
            self.failed.emit(f"Не поддерживается: {e or 'этот режим рендера ещё не реализован'}")
        except api.RenderError as e:
            self.failed.emit(f"Ошибка рендера: {e}")
        except Exception as e:  # окно не должно падать из-за backend
            self.failed.emit(f"Неожиданная ошибка: {e}")
        else:
            self.finished.emit(path)
