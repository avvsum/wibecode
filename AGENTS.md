# MY ROLE: ___   (A | B | C | D)

Если роль выше не заполнена, спроси "Какая у тебя роль: A, B, C или D?" и жди ответа.
Затем выполняй ТОЛЬКО task block своей роли. Блоки других ролей читай как контекст (чтобы знать их интерфейсы), но их код не пиши.

## Project
Desktop-приложение на Python 3.11: текстовое описание -> MP4 (1080x1920;
2D — 60 fps, 3D — 30 fps) для YouTube Shorts.
LLM НЕ рисует кадры и НЕ пишет код рендера. Она возвращает только JSON-спецификацию сцен. Движок валидирует JSON и рендерит видео через FFmpeg.

## Stack (не менять)
Python 3.11, FFmpeg (external binary), PySide6, pydantic, pytest, PyInstaller.

## MVP
- 2D: text, image, chart; 3D: те же типы и согласованный ниже say
- Output: MP4, UI: поле ввода, кнопка "Рендер", превью
- Out of scope: нейро-генерация видео, облако, аккаунты, timeline editor. Только рабочий минимум.

## Contract (единственный формат обмена, не менять без согласования)
```json
{
  "duration": 30,
  "render_mode": "2d",
  "scenes": [
    {"type": "text", "text": "Заголовок", "start": 0, "end": 5},
    {"type": "image", "path": "a.png", "start": 5, "end": 10},
    {"type": "chart", "data": [[1,2],[2,4]], "start": 10, "end": 15}
  ]
}
```
Валидация: start < end, end <= duration, известный type.

### render_mode (согласовано 25.10.2026)
- Необязательное поле верхнего уровня Spec, не отдельной сцены.
- Если поле отсутствует, Spec.render_mode == "2d"; старые JSON остаются валидными.
- Разрешены только строки "2d" и "3d", с учётом регистра.
- Любое другое значение (включая "4d", null, число и пустую строку) -> SpecError
  из api.parse_spec. Сообщение указывает поле render_mode и допустимые значения.
- "3d" успешно проходит parse_spec; правила валидации сцен остаются теми же.
- Пока 3D-движок не реализован, api.render_video для "3d" бросает
  NotImplementedError. Подменять 3D рендером 2D нельзя.
- Для "2d" и старых JSON: MP4 1080x1920, 60 fps (уточнение Льва 25.10.2026).
  Переход с прежних 30 fps выполняется согласованными PR A и D вместе.
- A реализует поле, валидацию и отказ рендера 3D; B показывает ошибку в UI;
  C учитывает поле в prompt; D поддерживает контракт и проверяет совместимость.
- Выбран Blender как внешний бинарник, движок Workbench (согласовано Львом
  25.10.2026). Blender устанавливается отдельно; Python-пакет bpy не требуется.
- D документирует внешние бинарники в docs; новые Python-зависимости, если
  понадобятся, записывает в requirements.txt. После готовности движка и UI D
  проверяет PyInstaller-сборку и сообщает размер всей папки dist/ShortsStudio
  в байтах и MiB. Итоговый MP4: 1080x1920; "2d" — 60 fps, "3d" — 30 fps.

### Расширение 3D (согласовано Львом 25.10.2026)
Реализация расширения идёт отдельными PR A/C/D; согласование не означает,
что 3D-движок уже готов. Пока он не реализован, действует NotImplementedError.

```json
{"duration": 4, "render_mode": "3d", "scenes": [
  {"type": "say", "who": "robot", "text": "Привет!", "shot": "close", "start": 0, "end": 4}
]}
```

- say разрешён только при render_mode == "3d"; в "2d" и без render_mode -> SpecError.
- Обязательны who, shot, text, start, end; text — непустая строка.
- who: только "robot" или "girl"; shot: только "wide", "medium" или "close".
  Значения регистрозависимы; другие значения и отсутствие поля -> SpecError.
- Правила времени те же: конечные числа, 0 <= start < end <= duration,
  без пересечений; смежные сцены допустимы.
- text/image/chart остаются валидными в обоих режимах. В готовом 3D-движке
  они отображаются как плоские вставки; смешивание с say допускается.
- A реализует схему и экспортирует SAY_WHO/SAY_SHOTS из src.api; C использует
  эти списки в prompt; D проверяет контракт, B передаёт выбранный режим в
  user_text до generate_spec, не подменяя режим готового JSON.
Decided: JSON, а не свободный код от LLM. Open: цвета, шрифты, анимации (выбирай сам).

### style: постобработка (согласовано владельцем репозитория)
- Необязательное поле верхнего уровня Spec: "none" (по умолчанию), "cinematic", "vivid",
  "bw", "sepia", "pixel", "retro", "warm", "cold", "dreamy". Другое значение -> SpecError.
- Выбирает LLM: стиль из запроса пользователя, иначе сама под тему и настроение.
  Пользователь в UI стиль не выбирает. Список экспортируется как api.STYLES.
- A: src/core/styles.py — фильтры FFmpeg; 2D и 3D применяют стиль в том же проходе
  сборки, размер 1080x1920, fps и длительность не меняются.
- Озвучка выравнивается по громкости до -14 LUFS (уровень YouTube).

### Озвучка (ElevenLabs, Chatterbox)
- Контракт JSON не меняется. Озвучиваются text (голос диктора) и say (голос по who).
- C: src/llm/tts.py — synthesize_spec(spec, out_dir, client) -> list[VoiceClip(path, start, end)];
  client: "elevenlabs" (ключ ELEVENLABS_API_KEY), "chatterbox" (локальная модель,
  необязательный requirements-chatterbox.txt) или TTSClient; FakeTTSClient для тестов, TTSError.
- A: api.add_voiceover(video_path, clips, out_path=None) -> str — FFmpeg добавляет
  AAC-дорожку, речь режется на end своей сцены, видео копируется без изменений.
- B: список «Озвучка» (нет / ElevenLabs / Chatterbox); ошибка озвучки не теряет готовое видео.
- Тесты не ходят в ElevenLabs: conftest удаляет ELEVENLABS_API_KEY.

## Public API (сигнатуры зафиксированы)
- api.parse_spec(raw: str) -> Spec            # raises SpecError
- api.render_video(spec: Spec, out_path: str, *, on_progress=None) -> str
- llm.generate_spec(user_text: str) -> str    # raw JSON
- llm.tts.synthesize_spec(spec: Spec, out_dir: str, client="elevenlabs") -> list[VoiceClip]
- api.add_voiceover(video_path: str, clips, out_path: str | None = None) -> str

### Прогресс и отмена (согласовано Львом 25.10.2026)
- on_progress необязателен; старые вызовы с двумя аргументами работают как прежде.
- В обоих режимах callback получает (done_frames, total_frames) в потоке рендера.
  total фиксирован; 0 означает неизвестное количество кадров. При известном total
  done не убывает и лежит в 0..total; последний вызов при успехе: done == total.
- Ровно False из callback отменяет рендер; None и True продолжают.
- При отмене выбрасывается RenderCancelled(RenderError), временные файлы убираются.
- Рендер пишет во временный файл и публикует out_path атомарно только при успехе.
  При ошибке/отмене новый out_path не остаётся недописанным, существующий сохраняется.
- SpecError, RenderError, ToolNotFoundError и RenderCancelled экспортируются из src.api.
  ToolNotFoundError наследуется от RenderError и FileNotFoundError.
- Реализация A/B и проверки D идут отдельными PR; согласование не означает готовность.

## Zones
A: src/core, src/api | B: src/ui, assets | C: src/llm | D: tests, scripts, docs, корень репо (integrator)
Общие файлы (config.py, README.md): перед правкой пиши в чат команды.

## Workflow
1. Читай соседние файлы и существующие тесты перед правкой.
2. Сначала plan из 3-5 пунктов, жди моего "ок", потом код.
3. Одна сессия = одна задача. Маленькие PR (до ~200 строк).
4. Ветка: feature/<name> или fix/<name>. В main не пушить.
5. Перед PR: git pull --rebase origin main, затем pytest. Красные тесты = не готово.

## Hard rules
- Работай только в своей зоне.
- Не добавляй dependencies без записи в requirements.txt.
- Никаких API keys, tokens, .env в коммитах.
- Не удаляй и не ослабляй чужие тесты.
- Не выдавай результат за готовый, если pytest падает.

## Output format
В конце коротко: что изменил, какие файлы затронул, как проверить.
