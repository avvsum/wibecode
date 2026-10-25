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

На Linux без видеокарты для Blender нужны `libegl1` и Mesa (`libgl1-mesa-dri`).

## Запуск

```powershell
python -m src.ui.main                               # окно приложения
python scripts/demo.py --out outputs/demo.mp4       # весь пайплайн без сети (LLM подменён)
python scripts/demo.py --duration 3                 # короткое демо для быстрой проверки
```

В окне: описание → выбор 2D/3D → «Рендер». Есть прогресс, «Отмена» и превью готового видео.
Ошибки (нет ключа, нет FFmpeg/Blender, неверный сценарий) показываются в статус-баре.
3D рендерится заметно дольше: около 0,6 с на кадр на 4 ядрах CPU без GPU,
то есть примерно 10 минут на 30 секунд видео.

Из кода:

```python
from src import api, llm

raw = llm.generate_spec("Ролик про рост продаж: заголовок, потом график")
spec = api.parse_spec(raw)                    # SpecError, если JSON неверный
api.render_video(spec, "outputs/video.mp4",
                 on_progress=lambda done, total: True)   # False отменяет рендер
```

## Формат сценария

```json
{
  "duration": 12,
  "render_mode": "3d",
  "scenes": [
    {"type": "text",  "text": "Заголовок", "start": 0, "end": 2},
    {"type": "say",   "who": "girl", "shot": "medium", "text": "Как это *сделано*?", "start": 2, "end": 5},
    {"type": "image", "path": "a.png", "start": 5, "end": 8},
    {"type": "chart", "data": [[1, 2], [2, 4], [3, 3]], "start": 8, "end": 12}
  ]
}
```

- `render_mode`: `"2d"` (по умолчанию) или `"3d"`.
- Сцены: `text`, `image`, `chart` — в обоих режимах; `say` — только в `"3d"`.
- `say`: `who` = `robot` | `girl`, `shot` = `wide` | `medium` | `close`. `*слово*` в тексте подсвечивается в субтитрах.
- Время: конечные числа, `0 ≤ start < end ≤ duration`, сцены не пересекаются, смежные допустимы.
  Промежутки заполняются фоном, длина видео всегда равна `duration`.
- `chart.data`: минимум две пары `[x, y]`.

Полный контракт, публичный API и правила команды — в [AGENTS.md](../AGENTS.md).

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
Размер на Linux (PySide6 6.12, 25.10.2026): 284 994 085 байт ≈ 271.8 MiB.
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
| `src/llm/` | prompt, клиент Claude, повтор запроса при ошибке, `FakeLLMClient` | C |
| `tests/`, `scripts/`, `docs/`, CI | тесты, демо, сборка, документация | D |

## Работа с Git

Правила в [AGENTS.md](../AGENTS.md):
- ветки `feature/<name>` или `fix/<name>`, в main напрямую не пушить;
- небольшие PR (~200 строк);
- перед PR: `git pull --rebase origin main` и полный `pytest`;
- красный CI не мержится.
