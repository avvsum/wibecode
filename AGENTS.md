# MY ROLE: ___   (A | B | C | D)

Если роль выше не заполнена, спроси "Какая у тебя роль: A, B, C или D?" и жди ответа.
Затем выполняй ТОЛЬКО task block своей роли. Блоки других ролей читай как контекст (чтобы знать их интерфейсы), но их код не пиши.

## Project
Desktop-приложение на Python 3.11: текстовое описание -> MP4 (1080x1920, 30 fps) для YouTube Shorts.
LLM НЕ рисует кадры и НЕ пишет код рендера. Она возвращает только JSON-спецификацию сцен. Движок валидирует JSON и рендерит видео через FFmpeg.

## Stack (не менять)
Python 3.11, FFmpeg (external binary), PySide6, pydantic, pytest, PyInstaller.

## MVP
- 3 типа сцен: text, image, chart
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
- Для "2d" и старых JSON сохраняется MP4 1080x1920, 30 fps.
- A реализует поле, валидацию и отказ рендера 3D; B показывает ошибку в UI;
  C учитывает поле в prompt; D поддерживает контракт и проверяет совместимость.
- Blender/moderngl ещё не выбраны. После выбора D записывает необходимые пакеты
  в requirements.txt (внешние бинарники — в docs), проверяет PyInstaller-сборку
  и сообщает размер всей папки dist/ShortsStudio в байтах и MiB.
Decided: JSON, а не свободный код от LLM. Open: цвета, шрифты, анимации (выбирай сам).

## Public API (сигнатуры зафиксированы)
- api.parse_spec(raw: str) -> Spec            # raises SpecError
- api.render_video(spec: Spec, out_path: str) -> str
- llm.generate_spec(user_text: str) -> str    # raw JSON

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
