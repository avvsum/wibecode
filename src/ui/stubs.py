"""Заглушки backend (src.api) и LLM (src.llm) для разработки UI без сети и ключа API.

Повторяют публичный API из AGENTS.md:
    api.parse_spec(raw: str) -> Spec            # raises SpecError
    api.render_video(spec: Spec, out_path: str, *, on_progress=None) -> str
    llm.connect(base_url, api_key) -> client    # здесь None
    llm.generate_spec(user_text: str, client=None) -> str    # raw JSON
    llm.generate_metadata(user_text: str, spec_json: str, client=None) -> VideoMetadata
"""
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace

WIDTH, HEIGHT, FPS = 1080, 1920, 60
SCENE_COLORS = {"text": "0x1e3a8a", "image": "0x065f46", "chart": "0x7c2d12"}
REQUIRED_FIELDS = {"text": "text", "image": "path", "chart": "data"}
RENDER_MODES = ("2d", "3d")
MODE_HINT = re.compile(r'\s*render_mode: "(\w+)"\s*$')


class SpecError(ValueError):
    """Спецификация не прошла валидацию."""


class RenderError(RuntimeError):
    """Видео не удалось собрать."""


class ToolNotFoundError(RenderError, FileNotFoundError):
    """Нет внешнего инструмента (FFmpeg)."""


class RenderCancelled(RenderError):
    """on_progress вернул False."""


class LLMError(Exception):
    """Провайдер LLM недоступен (нет ключа, сети и т. п.)."""


class SpecGenerationError(Exception):
    """Модель не дала валидный JSON за все попытки."""


@dataclass(frozen=True)
class Spec:
    duration: float
    scenes: list
    render_mode: str = "2d"


def connect(base_url: str = "", api_key: str = ""):
    return None  # заглушкам адрес и ключ API не нужны


def generate_spec(user_text: str, client=None) -> str:
    # Как и prompt C: явная подсказка render_mode в конце запроса задаёт режим.
    hint = MODE_HINT.search(user_text)
    text = user_text[:hint.start()] if hint else user_text
    # Если ввели JSON руками, отдаём как есть: удобно проверять ошибки SpecError из UI.
    if text.lstrip().startswith("{"):
        return text
    title = (text.strip().splitlines() or [""])[0][:60]
    spec = {
        "duration": 15,
        "scenes": [
            {"type": "text", "text": title, "start": 0, "end": 5},
            {"type": "chart", "data": [[1, 2], [2, 4], [3, 3]], "start": 5, "end": 10},
            {"type": "text", "text": "Конец", "start": 10, "end": 15},
        ],
    }
    if hint:
        spec["render_mode"] = hint.group(1)
    return json.dumps(spec, ensure_ascii=False)


@dataclass(frozen=True)
class VideoMetadata:
    title: str
    description: str
    tags: tuple

    def as_text(self) -> str:
        return (
            f"Название:\n{self.title}\n\n"
            f"Описание:\n{self.description}\n\n"
            f"Теги:\n{', '.join(self.tags)}"
        )


def generate_metadata(user_text: str, spec_json: str, client=None) -> VideoMetadata:
    hint = MODE_HINT.search(user_text)
    text = (user_text[:hint.start()] if hint else user_text).strip()
    title = (text.splitlines() or ["Ролик"])[0][:70]
    return VideoMetadata(title, f"{text[:200]}\n\n#Shorts", ("shorts", "заглушка"))


def parse_spec(raw: str) -> Spec:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SpecError(f"невалидный JSON: {e.msg} (строка {e.lineno})") from e
    if not isinstance(data, dict):
        raise SpecError("ожидался JSON-объект")
    duration = data.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise SpecError("duration должен быть положительным числом")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise SpecError("scenes должен быть непустым списком")
    render_mode = data.get("render_mode", "2d")
    if render_mode not in RENDER_MODES:
        raise SpecError(f"render_mode должен быть \"2d\" или \"3d\", получено {render_mode!r}")

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise SpecError(f"сцена {i}: ожидался объект")
        kind = scene.get("type")
        if kind not in REQUIRED_FIELDS:
            raise SpecError(f"сцена {i}: неизвестный type {kind!r}")
        if REQUIRED_FIELDS[kind] not in scene:
            raise SpecError(f"сцена {i} ({kind}): нет поля {REQUIRED_FIELDS[kind]!r}")
        start, end = scene.get("start"), scene.get("end")
        if not all(isinstance(t, (int, float)) for t in (start, end)):
            raise SpecError(f"сцена {i}: start и end должны быть числами")
        if not 0 <= start < end:
            raise SpecError(f"сцена {i}: нужно 0 <= start < end, получено {start}..{end}")
        if end > duration:
            raise SpecError(f"сцена {i}: end={end} больше duration={duration}")

    ordered = sorted(scenes, key=lambda s: s["start"])
    for prev, cur in zip(ordered, ordered[1:]):
        if cur["start"] < prev["end"]:
            raise SpecError(f"сцены {prev['start']}..{prev['end']} и {cur['start']}..{cur['end']} пересекаются")
    return Spec(duration=duration, scenes=ordered, render_mode=render_mode)


def render_video(spec: Spec, out_path: str, *, on_progress=None) -> str:
    """Каждая сцена рисуется цветным отрезком своего типа, пустые промежутки чёрным."""
    if spec.render_mode == "3d":
        raise NotImplementedError("3D-рендер пока не реализован")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ToolNotFoundError("FFmpeg не найден: установите его и добавьте в PATH")
    total = round(spec.duration * FPS)
    if on_progress is not None and on_progress(0, total) is False:
        raise RenderCancelled("рендер отменён")

    segments, cursor = [], 0
    for scene in spec.scenes:
        if scene["start"] > cursor:
            segments.append(("black", scene["start"] - cursor))
        segments.append((SCENE_COLORS[scene["type"]], scene["end"] - scene["start"]))
        cursor = scene["end"]
    if spec.duration > cursor:
        segments.append(("black", spec.duration - cursor))

    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for color, length in segments:
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s={WIDTH}x{HEIGHT}:r={FPS}:d={length}"]
    concat = "".join(f"[{i}:v]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[v]"
    tmp_path = f"{out_path}.part.mp4"  # как у A: out_path появляется только при успехе
    cmd += ["-filter_complex", concat, "-map", "[v]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", str(FPS), tmp_path]

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if result.returncode != 0:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise RenderError(f"FFmpeg завершился с ошибкой: {result.stderr.strip()[-300:]}")
    os.replace(tmp_path, out_path)
    if on_progress is not None:
        on_progress(total, total)
    return out_path


class TTSError(Exception):
    """Озвучка не удалась."""


def add_voiceover(video_path, clips, out_path=None):
    """Заглушка: без реплик видео не меняется."""
    return out_path or video_path


def add_music(video_path, track_path, out_path=None):
    """Заглушка: видео не меняется."""
    return out_path or video_path


api = SimpleNamespace(
    Spec=Spec, SpecError=SpecError, RenderError=RenderError, ToolNotFoundError=ToolNotFoundError,
    RenderCancelled=RenderCancelled, parse_spec=parse_spec, render_video=render_video,
    add_voiceover=add_voiceover, add_music=add_music, pick_music=lambda mood: None,
    user_music=lambda: [], import_music=lambda path: path,
)
# Заглушка озвучки не ходит в ElevenLabs и не создаёт реплик.
tts = SimpleNamespace(TTSError=TTSError, synthesize_spec=lambda spec, out_dir, client=None: [])
llm = SimpleNamespace(
    connect=connect, generate_spec=generate_spec, generate_metadata=generate_metadata, VideoMetadata=VideoMetadata,
    LLMError=LLMError, SpecGenerationError=SpecGenerationError, tts=tts,
)
