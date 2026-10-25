"""Фоновый пайплайн: описание -> JSON -> Spec -> MP4. Запускается в отдельном QThread."""
import tempfile

from PySide6.QtCore import QObject, Signal, Slot

from src.ui.backend import api, llm


def with_mode_hint(
    user_text: str, render_mode: str | None, environment: str = "studio", cast: str = "classic"
) -> str:
    """Дописывает выбранный в окне режим подсказкой для LLM.

    По AGENTS.md режим передаётся в user_text до generate_spec; в готовом JSON его не подменяем.
    None — «Авто»: подсказок нет, режим, окружение и персонажей модель выбирает по описанию.
    """
    if render_mode is None:
        return user_text
    hint = f'{user_text}\n\nrender_mode: "{render_mode}"'
    if render_mode == "3d":
        hint += f'\nenvironment: "{environment}"\ncast: "{cast}"'
    return hint


class RenderWorker(QObject):
    progress = Signal(str)
    spec_ready = Signal(object)  # проверенный Spec: окно показывает сценарий и ленту ещё до рендера
    frames = Signal(int, int)  # done, total из on_progress; total == 0 — неизвестно
    metadata = Signal(str, bool)  # текст для YouTube (или причина неудачи), удалось ли
    metadata_ready = Signal(object)  # VideoMetadata для кнопки публикации
    finished = Signal(str)  # путь к готовому MP4
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self, user_text: str, out_path: str, render_mode: str | None = None, voice: str | None = None,
        music: str | None = None, *, environment: str = "studio", cast: str = "classic",
        llm_base_url: str = "", llm_api_key: str = "",
    ):
        super().__init__()
        self._user_text = user_text
        self._out_path = out_path
        self._render_mode = render_mode  # "2d", "3d" или None — режим выбирает модель
        self._voice = voice  # провайдер озвучки: "elevenlabs", "chatterbox" или None
        self._environment = environment
        self._cast = cast
        self._music = music  # "auto" (настроение от модели), путь к своему треку или None
        self._llm_base_url = llm_base_url  # адрес OpenAI-совместимого API; пусто — из переменной окружения
        self._llm_api_key = llm_api_key
        self._client = None  # один клиент на запуск: модель выбирается один раз
        self._cancel_requested = False

    def cancel(self) -> None:
        """Вызывается из потока окна; рендер прервётся на ближайшем вызове on_progress."""
        self._cancel_requested = True

    def _on_progress(self, done: int, total: int) -> bool:
        self.frames.emit(done, total)
        return not self._cancel_requested

    def _emit_metadata(self, raw: str) -> None:
        """Название, описание и теги для YouTube; без них видео всё равно рендерится."""
        try:
            meta = llm.generate_metadata(self._user_text, raw, client=self._client)
        except (llm.LLMError, llm.SpecGenerationError) as e:
            self.metadata.emit(f"Не удалось подготовить название, описание и теги: {e}", False)
        else:
            self.metadata.emit(meta.as_text(), True)
            self.metadata_ready.emit(meta)

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Генерация сцен…")
            self._client = llm.connect(self._llm_base_url, self._llm_api_key)
            raw = llm.generate_spec(with_mode_hint(
                self._user_text, self._render_mode, self._environment, self._cast
            ), client=self._client)
            spec = api.parse_spec(raw)
            if self._render_mode and spec.render_mode != self._render_mode:  # JSON не переписываем
                self.failed.emit(
                    f"Модель вернула сценарий для режима {spec.render_mode.upper()}, "
                    f"а выбран {self._render_mode.upper()}. Попробуйте ещё раз или "
                    f"явно укажите в описании, что нужно {self._render_mode.upper()}-видео."
                )
                return
            if self._render_mode == "3d" and (
                spec.environment != self._environment or spec.cast != self._cast
            ):
                self.failed.emit(
                    "Модель вернула другое окружение или персонажей. "
                    "Попробуйте ещё раз: выбранные настройки должны совпадать со сценарием."
                )
                return
            self.spec_ready.emit(spec)
            if not self._cancel_requested:
                self.progress.emit("Название, описание и теги…")
                self._emit_metadata(raw)
            if self._cancel_requested:  # запрос к LLM не прервать, но рендер уже не начинаем
                raise api.RenderCancelled("отменено до рендера")
            style = getattr(spec, "style", "none")  # стиль выбирает модель, заглушки его не знают
            self.progress.emit("Рендер видео…" if style == "none" else f"Рендер видео, стиль {style}…")
            path = api.render_video(spec, self._out_path, on_progress=self._on_progress)
            if self._cancel_requested:
                raise api.RenderCancelled("отменено после рендера")
            if self._voice:
                self.progress.emit("Озвучка…")
                try:
                    with tempfile.TemporaryDirectory(prefix="shorts-voice-") as tmp:
                        clips = llm.tts.synthesize_spec(spec, tmp, self._voice)
                        if self._cancel_requested:
                            raise api.RenderCancelled("отменено во время озвучки")
                        api.add_voiceover(path, clips)
                except api.RenderCancelled:
                    raise
                except (llm.tts.TTSError, api.RenderError) as e:
                    self.failed.emit(f"Видео готово без озвучки ({path}). Озвучка не удалась: {e}")
                    return
            if self._cancel_requested:
                raise api.RenderCancelled("отменено до добавления музыки")
            mood = getattr(spec, "music", "none")  # настроение выбирает модель, заглушки его не знают
            track = api.pick_music(mood) if self._music == "auto" else self._music
            if track:
                self.progress.emit("Музыка…" if self._music != "auto" else f"Музыка: {mood}…")
                try:
                    if self._music != "auto" and track not in api.user_music():
                        track = api.import_music(track)  # «Свой файл…» остаётся в списке треков
                    api.add_music(path, track)
                except api.RenderError as e:
                    self.failed.emit(f"Видео готово без музыки ({path}). Музыка не добавилась: {e}")
                    return
            if self._cancel_requested:
                raise api.RenderCancelled("отменено во время добавления музыки")
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


class PublishWorker(QObject):
    """Загрузка готового MP4 на YouTube в отдельном QThread."""

    uploaded = Signal(int, int)  # отправлено байт, всего байт
    finished = Signal(str)  # ссылка на ролик
    failed = Signal(str)

    def __init__(self, video_path: str, title: str, description: str, tags=()):
        super().__init__()
        self._video_path = video_path
        self._title = title
        self._description = description
        self._tags = list(tags)

    @Slot()
    def run(self) -> None:
        from src.publish import PublishError, upload  # библиотеки Google нужны только здесь

        try:
            url = upload(self._video_path, self._title, self._description, tags=self._tags,
                         on_progress=self.uploaded.emit)
        except PublishError as e:
            self.failed.emit(str(e))
        except Exception as e:  # окно не должно падать из-за сети или Google
            self.failed.emit(f"Неожиданная ошибка публикации: {e}")
        else:
            self.finished.emit(url)
