# ShortsStudio (wibecode)

[← Презентация проекта и быстрый старт](../README.md) · [Как работает и запускается 3D](3d.md)

Настольное приложение: текстовое описание → вертикальное видео MP4 для YouTube Shorts.

LLM (Claude) превращает описание в JSON-сценарий, движок проверяет его и рендерит видео.
Модель не рисует кадры и не пишет код, она возвращает только JSON.

| Режим | Как рендерится | Видео |
|---|---|---|
| `2d` (по умолчанию) | Pillow + FFmpeg: текст, картинки, графики | 1080×1920, 60 fps |
| `3d` | Blender (Workbench): студия, робот и девушка говорят реплики; text/image/chart — плоские вставки | 1080×1920, 30 fps |

## Установка

Нужны **Python 3.11**, **FFmpeg** (с ffprobe) и, для 3D, **Blender 4.2+**
(проверено на 5.0.1). FFmpeg и Blender — внешние программы, pip их не ставит.
Python-пакет `bpy` не нужен.

Windows (PowerShell, из корня репозитория):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ffmpeg -version
blender --version   # только для 3D
```

Linux/macOS: `python3.11 -m venv .venv` и `.venv/bin/python` вместо Windows-путей.
С uv: `uv venv --python 3.11 .venv`.

Переменные окружения:

| Переменная | Зачем |
|---|---|
| `ANTHROPIC_API_KEY` | ключ Claude для генерации сценария. Не храните его в файлах проекта |
| `WIBECODE_BLENDER` | путь к `blender`, если его нет в PATH |
| `ELEVENLABS_API_KEY` | ключ ElevenLabs, если выбрана озвучка ElevenLabs |
| `WIBECODE_YT_CLIENT_SECRET` | путь к OAuth-клиенту YouTube, если он не в `~/.shortsstudio/client_secret.json` |
| `ELEVENLABS_VOICE_NARRATOR`, `_ROBOT`, `_GIRL` | необязательно: свои voice ID вместо стандартных |
| `CHATTERBOX_VOICE_NARRATOR`, `_ROBOT`, `_GIRL` | необязательно: путь к .wav 5–10 с, чей голос клонирует Chatterbox |
| `CHATTERBOX_LANGUAGE` | необязательно: язык Chatterbox (`ru`, `en`, …); по умолчанию по тексту |

На Linux без видеокарты для Blender нужны `libegl1` и Mesa (`libgl1-mesa-dri`).

## Запуск

```powershell
python -m src.ui.main                               # окно приложения
python scripts/demo.py --out outputs/demo.mp4       # весь пайплайн без сети (LLM подменён)
python scripts/demo.py --duration 3                 # короткое демо для быстрой проверки
```

В окне: описание → выбор 2D/3D → «Рендер». Есть прогресс, «Отмена» и превью готового видео.
До рендера Claude готовит название, описание с хэштегами (#Shorts) и теги для YouTube;
кнопка «Копировать для YouTube» кладёт их в буфер обмена.
Ошибки (нет ключа, нет FFmpeg/Blender, неверный сценарий) показываются в статус-баре.
Список «Озвучка» после рендера добавляет голос: сцены `text` читает диктор,
реплики `say` — голоса robot/girl. Речь режется на конце своей сцены.
Если озвучка не удалась, видео остаётся без звука, а причина видна в статус-баре.

- **ElevenLabs** — облако, нужен `ELEVENLABS_API_KEY`, тратит символы аккаунта.
- **Chatterbox (локально)** — бесплатная модель Resemble AI на вашем компьютере, без ключа.
  Ставится отдельно: `pip install -r requirements-chatterbox.txt` (PyTorch, несколько ГБ).
  Первый запуск скачивает модель с Hugging Face; без видеокарты озвучка медленная
  (минуты на ролик). Голос у всех ролей встроенный, пока не задан `CHATTERBOX_VOICE_*`.
  В собранный `ShortsStudio` Chatterbox не входит — только запуск из исходников.

Тесты не ходят ни в ElevenLabs, ни в Chatterbox: используются заглушки.
3D рендерится заметно дольше: около 0,6 с на кадр на 4 ядрах CPU без GPU,
то есть примерно 10 минут на 30 секунд видео.

Из кода:

```python
from src import api, llm

raw = llm.generate_spec("Ролик про рост продаж: заголовок, потом график")
spec = api.parse_spec(raw)                    # SpecError, если JSON неверный
api.render_video(spec, "outputs/video.mp4",
                 on_progress=lambda done, total: True)   # False отменяет рендер
clips = llm.tts.synthesize_spec(spec, "outputs/voice", "chatterbox")  # или "elevenlabs"
api.add_voiceover("outputs/video.mp4", clips)             # AAC-дорожка в тот же MP4
meta = llm.generate_metadata("Ролик про рост продаж", raw)  # title, description, tags
print(meta.as_text())
```

## Публикация на YouTube

После рендера в окне активна кнопка **«Опубликовать на YouTube»**. Ролик загружается
в фоне с прогрессом, по готовности ссылка `youtube.com/shorts/…` открывается в браузере.
Вертикальное видео до 3 минут YouTube сам делает Shorts.
Заголовок — первая строка описания (до 100 символов), описание ролика — весь текст.

Настройка один раз (Google Cloud Console, тот же Google-аккаунт, что у канала):

1. Создать проект и включить **YouTube Data API v3**.
2. **Google Auth Platform**: создать экран согласия (External), статус **Testing**,
   в **Audience → Test users** добавить свой Gmail.
3. **Clients → Create client → Desktop app** → **Download JSON**.
4. Сохранить файл как `~/.shortsstudio/client_secret.json`
   (Windows: `C:\Users\<имя>\.shortsstudio\client_secret.json`) или указать путь в
   `WIBECODE_YT_CLIENT_SECRET`. **Не кладите его в репозиторий.**

При первой публикации откроется браузер: войдите и разрешите доступ. Google предупредит,
что приложение не проверено: «Дополнительно» → «Перейти». Токен сохраняется в
`~/.shortsstudio/youtube_token.json`. В режиме Testing он живёт 7 дней, потом вход повторяется.

Ограничения, пока проект не прошёл аудит YouTube API:
- все загруженные через API ролики **приватные**, открыть их можно вручную в YouTube Studio;
- квота около 10 000 единиц в день, это примерно **6 загрузок**.

Из кода: `from src.publish import upload; upload("outputs/video.mp4", "Заголовок")`.

## Формат сценария

```json
{
  "duration": 12,
  "render_mode": "3d",
  "style": "retro",
  "scenes": [
    {"type": "text",  "text": "Заголовок", "start": 0, "end": 2},
    {"type": "say",   "who": "girl", "shot": "medium", "text": "Как это *сделано*?", "start": 2, "end": 5},
    {"type": "image", "path": "a.png", "start": 5, "end": 8},
    {"type": "chart", "data": [[1, 2], [2, 4], [3, 3]], "start": 8, "end": 12}
  ]
}
```

- `render_mode`: `"2d"` (по умолчанию) или `"3d"`.
- `style`: обработка видео, по умолчанию `"none"`; значения — в разделе «Стиль видео» ниже.
- Сцены: `text`, `image`, `chart` — в обоих режимах; `say` — только в `"3d"`.
- `say`: `who` = `robot` | `girl`, `shot` = `wide` | `medium` | `close`. `*слово*` в тексте подсвечивается в субтитрах.
- Время: конечные числа, `0 ≤ start < end ≤ duration`, сцены не пересекаются, смежные допустимы.
  Промежутки заполняются фоном, длина видео всегда равна `duration`.
- `chart.data`: минимум две пары `[x, y]`.

Полный контракт, публичный API и правила команды — в [AGENTS.md](../AGENTS.md).

## Стиль видео

Модель сама выбирает обработку всего ролика и пишет её в поле `style` сценария:
`cinematic`, `vivid`, `bw`, `sepia`, `pixel` (пиксель-арт), `retro` (VHS), `warm`, `cold`,
`dreamy` или `none`. Попросите в описании («в стиле пиксель-арт», «как старая VHS») —
она возьмёт этот стиль; не попросите — подберёт под тему. Выбранный стиль виден
в статус-баре во время рендера. Озвучка выравнивается по громкости до −14 LUFS.

## Тесты

```powershell
python -m pytest                       # всё, нужны FFmpeg и Blender
python -m pytest -m "not blender"      # без Blender
python -m pytest -m "not integration"  # быстро, без реального рендера
```

Тесты не ходят в сеть: LLM подменяется `FakeLLMClient`, сетевые вызовы блокируются.
Маркеры: `integration` рендерит настоящие MP4 и проверяет их ffprobe, `blender` — настоящий 3D-рендер.
skip/xfail не используются. CI (GitHub Actions, Python 3.11) ставит FFmpeg и Blender
и прогоняет всё на каждый PR и push в main.

## Сборка

```powershell
python scripts/build.py --check   # проверить файлы и зависимости
python scripts/build.py           # PyInstaller → dist/ShortsStudio/
```

Сборка делается на целевой ОС (не кросс-компиляция). Передавайте всю папку
`dist/ShortsStudio`. FFmpeg и Blender в неё не входят и должны быть установлены на машине.
Ключи и `.env` в сборку не попадают.
Размер на Linux (PySide6 6.12, с публикацией на YouTube, 25.10.2026): 302 891 904 байт ≈ 288.9 MiB.
Размер на Windows: замерить так:

```powershell
$b = (Get-ChildItem dist/ShortsStudio -File -Recurse | Measure-Object Length -Sum).Sum
"{0} bytes = {1:N1} MiB" -f $b, ($b / 1MB)
```

## Структура

| Путь | Что | Зона |
|---|---|---|
| `src/core/schema.py` | модели сценария и валидация (pydantic) | A |
| `src/core/renderer.py` | 2D-рендер, прогресс и отмена, выбор движка по `render_mode` | A |
| `src/core/render3d/` | 3D: сцена для Blender, субтитры, сборка видео | A |
| `src/api/` | публичный API: `parse_spec`, `render_video`, исключения, `SAY_WHO`/`SAY_SHOTS` | A |
| `src/ui/` | окно PySide6, фоновый рендер в QThread, заглушки для работы без сети | B |
| `src/publish/` | публикация на YouTube: OAuth, загрузка с прогрессом, понятные ошибки | A |
| `src/llm/` | prompt, клиент Claude, повтор запроса при ошибке, `FakeLLMClient` | C |
| `tests/`, `scripts/`, `docs/`, CI | тесты, демо, сборка, документация | D |

## Работа с Git

Правила в [AGENTS.md](../AGENTS.md):
- ветки `feature/<name>` или `fix/<name>`, в main напрямую не пушить;
- небольшие PR (~200 строк);
- перед PR: `git pull --rebase origin main` и полный `pytest`;
- красный CI не мержится.
