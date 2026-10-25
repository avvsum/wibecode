# wibecode: описание → YouTube Shorts

Python 3.11, PySide6, pydantic, внешний FFmpeg. Результат: MP4, 1080×1920, 30 fps.
LLM возвращает JSON; кадры строит движок. Сетевой провайдер реализуется участником C.

## Состояние интеграции

В `main` включены backend A (PR #6), LLM C с render_mode (PR #7) и каркас D.
Проверка 25.10.2026 на Python 3.11.16: main `b12c1864` + head PR #7 `5094e1df`
+ tests/scripts D `3dbe3486`: **60 passed**, включая старые JSON без render_mode
и реальные MP4 на 3/30 секунд. Сеть в тестах блокируется.
Merge PR #7: `784ee16e`; отдельное демо PR #6: 1080x1920, 30/1 fps, 30.000000 с.

Тесты D опубликованы отдельно: PR #3 (схема/режимы) и #4 (LLM/MP4/скрипты).
После включения A они могут пройти проверку и выйти из draft; skip/xfail
не используются. UI B ещё не опубликован, поэтому сборка не проверена.
В CODEOWNERS для зоны D указан `w5sk`; реальные логины A/B/C ещё нужно заполнить.

## Подготовка (PowerShell, из корня репозитория)

Установите Python 3.11 и FFmpeg с ffprobe, добавьте исполняемые файлы в PATH.
FFmpeg — внешний бинарник, pip его не устанавливает.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

Если установлен uv: `uv venv --python 3.11 .venv`, затем та же установка зависимостей.
Linux/macOS: используйте `python3.11` и `.venv/bin/python` вместо Windows-путей.

## Контракт для A/B/C

`render_mode` — необязательное поле верхнего уровня: только `"2d"` или `"3d"`.
Без поля используется `"2d"`; старые JSON работают в прежнем формате. `"3d"`
валидируется, но `render_video` пока бросает `NotImplementedError`. Иные значения,
включая `"4d"` и `null`, приводят к `SpecError`. Точный контракт — в AGENTS.md.
Сообщение для командного чата: [TEAM_UPDATE_RENDER_MODE.md](TEAM_UPDATE_RENDER_MODE.md).

Лев согласовал расширение `say` только для `"3d"`: обязательны `who`
(`"robot"`/`"girl"`), `shot` (`"wide"`/`"medium"`/`"close"`), непустой `text`,
`start`, `end`. Обычные text/image/chart сохраняются в обоих режимах и могут
чередоваться с say. A экспортирует списки `SAY_WHO`/`SAY_SHOTS` для prompt C.
Это целевой контракт; в main после PR #7 say и 3D-движок ещё не реализованы.
Режим UI передаётся в user_text до generate_spec; готовый JSON не переписывается.

- A экспортирует `SpecError`, `parse_spec(raw: str) -> Spec`,
  `render_video(spec: Spec, out_path: str) -> str` из `src.api`.
- C реализует `generate_spec(user_text: str) -> str` в `src.llm.client`
  и экспортирует его из `src.llm`. На невалидный ответ допускаются две повторные
  попытки: максимум три запроса. Исправляющий запрос содержит текст `SpecError`;
  итоговая ошибка после исчерпания попыток также содержит причину валидации.
- B предоставляет `src/ui/main.py`, запускаемый как `python -m src.ui.main`.

Существующий тестовый интерфейс C в `feature/llm-client`:

```python
FakeLLMClient(responses: list[str])
client.complete(system: str, messages: list[dict]) -> str
fake.calls  # снимки истории сообщений для каждого запроса
```

Фейк выдаёт ответы последовательно. Тесты и офлайн-демо подменяют фабрику
`src.llm.client.AnthropicClient` фейком через monkeypatch/patch и вызывают
обычный `generate_spec(user_text)`. Сетевой ключ при этом не нужен; фактический
`parse_spec` участника A используется для проверки каждого ответа и retry.
Для сетевого запуска C читает `ANTHROPIC_API_KEY` из окружения; SDK включён
в requirements.txt. Ключи не сохраняйте в файлах проекта.

Тесты D требуют отклонять пустой список сцен и пересечения интервалов; смежные
интервалы допустимы. Эти случаи взяты из task block D. Остальные правила:
`start < end`, `end <= duration`, известный `type`, содержимое по типу сцены.
В примере общего контракта остаётся незаполненный хвост, поэтому равенство последнего
`end` и `duration` не требуется. Для такого хвоста A должен сохранить общую длину видео.

## Проверки и запуск

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/demo.py --out outputs/demo.mp4
.\.venv\Scripts\python.exe -m src.ui.main
```

Демо по умолчанию создаёт 30 секунд с text/image/chart и временной картинкой;
`--duration 3` ускоряет ручную проверку. Вызов LLM в демо подменён фейком.
Тесты блокируют сетевые соединения. Integration реально рендерит 3 и 30 секунд,
проверяет существование файла, MP4-контейнер, длительность (±0,1 с), разрешение и fps
через ffprobe; включает кириллицу и пробелы в путях. Совместный прогон с A прошёл.
`-m "not integration"` подходит для быстрой разработки, но не заменяет полный прогон.
CI на Python 3.11 устанавливает FFmpeg и выполняет полный pytest, включая
существующие тесты из `src/llm/tests`.

## Сборка

```powershell
.\.venv\Scripts\python.exe scripts/build.py --check
.\.venv\Scripts\python.exe scripts/build.py
```

PyInstaller создаёт `dist/ShortsStudio/ShortsStudio.exe` на Windows. Передавайте всю
папку `dist/ShortsStudio`; FFmpeg/ffprobe должны быть в PATH на целевой машине.
Сборка выполняется на целевой ОС, не является кросс-компиляцией.
Ключи и .env в сборку не добавляются. Запуск собранного UI проверяется после реализации B.
Для 3D выбран внешний Blender с движком Workbench. Blender устанавливается
отдельно от requirements.txt и папки приложения; пакет bpy через pip не нужен.
Добавьте Blender в PATH и проверьте `blender --version`. Backend A запускает
его в фоне через `blender -b -P <script>`; параметры описаны в
[Blender Manual](https://docs.blender.org/manual/en/4.2/advanced/command_line/arguments.html).
Версия Blender и проверенные системные зависимости будут зафиксированы вместе
с backend A; наличие бинарника само по себе не подтверждает готовность 3D.

После готовности A/B D запускает сборку, проверяет запуск приложения и измеряет
именно всю папку dist/ShortsStudio, отдельно от внешних Blender/FFmpeg:

```powershell
$bundleBytes = (Get-ChildItem -LiteralPath dist/ShortsStudio -File -Recurse |
    Measure-Object -Property Length -Sum).Sum
[pscustomobject]@{ Bytes = $bundleBytes; MiB = $bundleBytes / 1MB }
```

В отчёте указываются байты и MiB (1 MiB = 1048576 байт). Сейчас сборка и её размер
не проверены: UI B и 3D-backend A ещё не интегрированы.

## Работа с Git

Зоны и правила находятся в AGENTS.md. Работайте в `feature/<name>` или `fix/<name>`.
Перед PR: сохраните свою работу коммитом, выполните `git pull --rebase origin main`,
затем полный `python -m pytest`. Красные проверки блокируют готовность и merge.
Разделяйте изменения на небольшие PR до ~200 строк. Прямой push в main запрещён.
Владельцы репозитория должны включить обязательную проверку `pytest` в правилах main;
сам workflow не запрещает ручной merge без branch protection.
