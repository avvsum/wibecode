"""Prompts for turning a user description into a scene spec (JSON contract)."""

import re

from src.api import CASTS, ENVIRONMENTS, SAY_SHOTS, SAY_WHO, STYLES
from src.llm.metadata import DESCRIPTION_MAX, TITLE_MAX


def _quoted(values) -> str:
    return ", ".join(f'"{v}"' for v in values)


EXAMPLE_SPEC = """{
  "duration": 15,
  "style": "vivid",
  "scenes": [
    {"type": "text", "text": "Заголовок", "start": 0, "end": 5},
    {"type": "image", "path": "a.png", "start": 5, "end": 10},
    {"type": "chart", "data": [[1, 2], [2, 4], [3, 3]], "start": 10, "end": 15}
  ]
}"""

EXAMPLE_3D_SPEC = """{
  "duration": 10,
  "render_mode": "3d",
  "style": "cinematic",
  "environment": "room",
  "cast": "knight_mage",
  "scenes": [
    {"type": "text", "text": "Как работает Wi-Fi", "start": 0, "end": 3},
    {"type": "say", "who": "robot", "text": "Wi-Fi — это радиоволны.", "shot": "close", "start": 3, "end": 7},
    {"type": "say", "who": "girl", "text": "А роутер их раздаёт?", "shot": "medium", "start": 7, "end": 10}
  ]
}"""

SYSTEM_PROMPT = f"""Ты сценарист коротких вертикальных видео (YouTube Shorts, 1080x1920).
По описанию пользователя составь спецификацию сцен.

Ответ: ТОЛЬКО один JSON-объект. Без markdown, без ```, без пояснений до или после.

Формат (строго, других полей не добавляй):
- "duration": число секунд всего видео (от 5 до 60).
- "render_mode": необязательное поле, "2d" или "3d". Без него видео 2D, поэтому
  обычно его не указывай. "3d" ставь, только если пользователь прямо просит
  3D-видео; если 3D лишь тема ролика (например, 3D-печать), это 2D. Если в запросе
  явно указано render_mode: "3d" или render_mode: "2d", используй именно это значение.
  Только эти две строки, в нижнем регистре; null и другие значения запрещены.
- "style": обработка всего видео, одно из {_quoted(STYLES)}.
  Если пользователь назвал стиль или настроение (пиксели, ретро, VHS, чёрно-белое,
  кино, тёплое…), возьми подходящий. Иначе придумай сам под тему и настроение:
  cinematic — драма, истории; vivid — цифры, графики, реклама; bw — серьёзное,
  история; sepia — старина, воспоминания; pixel — игры, техника, мемы; retro — 80-е,
  90-е, ностальгия; warm — уют, еда, лето; cold — зима, наука, космос; dreamy —
  мечты, романтика; none — только если обработка явно не нужна.
- "environment": необязательное окружение 3D, одно из {_quoted(ENVIRONMENTS)}.
  studio — исходная студия; room — уютная комната; forest — лесная поляна;
  dungeon — подземелье; space — космическая база; city — городская площадь.
  Без поля используется studio.
- "cast": необязательная пара персонажей 3D, одно из {_quoted(CASTS)}.
  classic — робот и девушка; knight_mage — рыцарь и маг; rogue_duo — два разбойника
  (один в капюшоне); barbarian_mage — варвар и маг; ranger_knight — лучник
  и рыцарь. Без поля используется classic.
  Поле who всегда robot или girl: это первый и второй участник выбранной пары.
  Явные подсказки environment: "..." и cast: "..." из интерфейса имеют приоритет
  над описанием; обязательно верни выбранные значения в JSON. В 2D поля не нужны.
- "scenes": непустой список сцен. Каждая сцена ровно одного из типов:
  - {{"type": "text", "text": <строка>, "start": <число>, "end": <число>}}
  - {{"type": "image", "path": <путь к файлу>, "start": <число>, "end": <число>}}
  - {{"type": "chart", "data": [[x, y], ...], "start": <число>, "end": <число>}}
  - {{"type": "say", "who": <персонаж>, "text": <реплика>, "shot": <план>, "start": <число>, "end": <число>}}
    — только при "render_mode": "3d".

Правила:
- для каждой сцены start < end и end <= duration;
- сцены идут по порядку и не пересекаются;
- text: короткая фраза, до ~60 символов, чтобы читалась на экране телефона;
- image: только если пользователь сам назвал файл картинки, иначе используй text;
- chart: data — список пар чисел [x, y], минимум 2 точки;
- say: реплика персонажа, только при "render_mode": "3d" (в 2D и без render_mode
  запрещена); who — одно из {_quoted(SAY_WHO)}; shot — план камеры, одно из
  {_quoted(SAY_SHOTS)}; все поля обязательны; text — короткая реплика обычным
  текстом, без разметки;
- в 3D-ролике основа — реплики say; text, image и chart там тоже допустимы;
- text и say могут озвучиваться голосом: текст должен успеть прозвучать за время
  сцены, не больше ~2 слов на секунду (end - start).

Пример 2D:
{EXAMPLE_SPEC}

Пример 3D:
{EXAMPLE_3D_SPEC}
"""


def fix_message(error: str) -> str:
    """User message asking the model to fix a spec rejected by the validator."""
    return (
        "Твой JSON не прошёл проверку. Ошибка:\n"
        f"{error}\n\n"
        "Исправь и верни ТОЛЬКО исправленный JSON-объект целиком, без пояснений."
    )


EXAMPLE_METADATA = """{
  "title": "Продажи выросли втрое: итоги года за 15 секунд",
  "description": "Короткий разбор итогов года: как росли продажи по кварталам и что стало главным драйвером.\\n\\n#Shorts #бизнес #продажи #аналитика",
  "tags": ["рост продаж", "итоги года", "продажи по кварталам", "бизнес аналитика", "отчёт о продажах", "shorts"]
}"""

METADATA_PROMPT = f"""Ты редактор YouTube Shorts. По описанию ролика и его сценарию (JSON сцен)
подготовь метаданные для публикации.

Ответ: ТОЛЬКО один JSON-объект. Без markdown, без ```, без пояснений до или после.

Формат (строго, других полей не добавляй):
- "title": название, лучше до 70 символов (максимум {TITLE_MAX}); суть ролика в первых словах,
  без кликбейта и без кавычек вокруг всего названия;
- "description": 2–4 коротких предложения о том, что зритель увидит, затем пустая строка
  и строка из 3–5 хэштегов, первый — #Shorts; всего не больше {DESCRIPTION_MAX} символов;
- "tags": список из 5–15 тегов — ключевые слова и короткие фразы, по которым ищут такой
  ролик; без символа #, без повторов; все теги вместе не длиннее 450 символов.

Правила:
- пиши на языке описания пользователя;
- опирайся только на содержание ролика, не обещай того, чего в нём нет;
- не используй символы < и >.

Пример:
{EXAMPLE_METADATA}
"""

# The UI appends this hint for generate_spec; it says nothing about the video's topic.
_MODE_HINT_RE = re.compile(
    r'(?:\s*(?:render_mode|environment|cast):\s*"[a-z0-9_]+")+\s*$'
)


def metadata_request(user_text: str, spec_json: str) -> str:
    """User message asking for YouTube metadata of a generated spec."""
    description = _MODE_HINT_RE.sub("", user_text).strip()
    return (
        f"Описание ролика от пользователя:\n{description}\n\n"
        f"Сценарий ролика (JSON):\n{spec_json}"
    )
