"""Spec -> MP4. Each scene becomes a still frame (Pillow), FFmpeg turns them into video."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Callable, Optional, Protocol

from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.core.schema import ChartScene, ImageScene, Spec, TextScene

WIDTH, HEIGHT = 1080, 1920
FPS = 60  # 2D output; the 3D backend renders at 30 fps
BG = (18, 18, 28)
FG = (240, 240, 245)
ACCENT = (255, 196, 0)
GRID = (70, 70, 90)
FADE = 0.3  # seconds of fade in/out per scene

FONT_CANDIDATES = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "arialbd.ttf",  # Windows
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",  # macOS
)


class RenderError(RuntimeError):
    """Spec is valid but the video could not be produced (missing file, FFmpeg failure)."""


class ToolNotFoundError(RenderError, FileNotFoundError):
    """A required external program (FFmpeg, Blender) is not installed or not in PATH."""


class RenderCancelled(RenderError):
    """on_progress returned False; out_path was left untouched."""


# on_progress(done_frames, total_frames) -> bool. total is fixed for one render
# (0 if unknown), done grows from 0 to total; returning False cancels.
ProgressCallback = Callable[[int, int], Optional[bool]]


class Renderer(Protocol):
    def render(
        self, spec: Spec, out_path: str, on_progress: Optional[ProgressCallback] = None
    ) -> str:
        """Write spec as a video to out_path and return the path."""
        ...


def _report(on_progress: Optional[ProgressCallback], done: int, total: int) -> None:
    if on_progress is not None and on_progress(done, total) is False:
        raise RenderCancelled("рендер отменён")


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _blank() -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), BG)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str] | None:
    """Greedy word wrap by pixel width; None if a single word does not fit."""
    lines = []
    for para in text.splitlines() or [""]:
        line = ""
        for word in para.split():
            if draw.textlength(word, font=font) > max_width:
                return None
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _text_frame(scene: TextScene) -> Image.Image:
    img = _blank()
    draw = ImageDraw.Draw(img)
    max_width, max_height = int(WIDTH * 0.85), int(HEIGHT * 0.7)
    for size in (110, 96, 80, 64, 52, 40, 32):
        font = _font(size)
        lines = _wrap(draw, scene.text, font, max_width)
        if lines and len(lines) * size * 1.3 <= max_height:
            break
    else:  # very long words or text: hard-wrap at the smallest size
        lines = textwrap.wrap(scene.text, width=max_width // int(size * 0.6)) or [""]
    text = "\n".join(lines)
    draw.multiline_text(
        (WIDTH / 2, HEIGHT / 2), text, font=font, fill=FG, anchor="mm", align="center", spacing=24
    )
    return img


def _image_frame(scene: ImageScene) -> Image.Image:
    path = Path(scene.path)
    try:
        with Image.open(path) as src:
            pic = ImageOps.exif_transpose(src).convert("RGB")
    except FileNotFoundError:
        raise RenderError(f"картинка не найдена: {scene.path}") from None
    except OSError as e:
        raise RenderError(f"не удалось открыть картинку {scene.path}: {e}") from None
    pic = ImageOps.contain(pic, (WIDTH - 80, HEIGHT - 160))
    img = _blank()
    img.paste(pic, ((WIDTH - pic.width) // 2, (HEIGHT - pic.height) // 2))
    return img


def _nice_step(span: float, ticks: int = 4) -> float:
    """Round step (1, 2, 2.5 or 5 times a power of ten) covering span in ~ticks steps."""
    raw = span / ticks
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)


def _number(value: float) -> str:
    text = f"{value:,.10g}".replace(",", "\u202f")  # narrow no-break space: 23 817
    return "0" if text == "-0" else text


def _chart_frame(scene: ChartScene) -> Image.Image:
    img = _blank()
    draw = ImageDraw.Draw(img)
    xs = [x for x, _ in scene.data]
    ys = [y for _, y in scene.data]
    x0, x1 = min(xs), max(xs)
    if x1 == x0:
        x0, x1 = x0 - 1, x1 + 1
    lo, hi = min(min(ys), 0), max(max(ys), 0)
    step = _nice_step(hi - lo or 1)
    y0, y1 = math.floor(lo / step) * step, math.ceil(hi / step) * step
    y1 = y1 if y1 > y0 else y0 + step
    ticks = [y0 + k * step for k in range(round((y1 - y0) / step) + 1)]

    label = _font(40)
    left = 40 + max(draw.textlength(_number(t), font=label) for t in ticks) + 20
    right, top, bottom = WIDTH - 80, 460, HEIGHT - 460

    def px(x: float, y: float) -> tuple[float, float]:
        return (
            left + (x - x0) / (x1 - x0) * (right - left),
            bottom - (y - y0) / (y1 - y0) * (bottom - top),
        )

    for y in ticks:
        _, py = px(x0, y)
        draw.line([(left, py), (right, py)], fill=GRID, width=2)
        draw.text((left - 20, py), _number(y), font=label, fill=FG, anchor="rm")
    every = max(1, math.ceil(len(xs) / 8))  # at most ~8 x labels
    for x in sorted(set(xs))[::every]:
        draw.text((px(x, y0)[0], bottom + 30), _number(x), font=label, fill=FG, anchor="mt")
    points = [px(x, y) for x, y in sorted(scene.data)]
    draw.line(points, fill=ACCENT, width=10, joint="curve")
    for cx, cy in points:
        draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=ACCENT)
    return img


FRAMES = {TextScene: _text_frame, ImageScene: _image_frame, ChartScene: _chart_frame}


def _segments(spec: Spec) -> list[tuple[Image.Image, int, bool]]:
    """Timeline as (frame, length in frames, fade) with black gaps between scenes."""
    segments = []
    cursor = 0
    for scene in sorted(spec.scenes, key=lambda s: s.start):
        start, end = round(scene.start * FPS), round(scene.end * FPS)
        if start > cursor:
            segments.append((_blank(), start - cursor, False))
        if end > max(start, cursor):
            segments.append((FRAMES[type(scene)](scene), end - max(start, cursor), True))
        cursor = max(cursor, end)
    total = round(spec.duration * FPS)
    if total > cursor:
        segments.append((_blank(), total - cursor, False))
    return segments


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise ToolNotFoundError("FFmpeg не найден: установите его и добавьте в PATH")
    return exe


class FFmpegRenderer:
    """2D renderer: still frames per scene, fades, H.264 MP4 1080x1920."""

    def render(
        self, spec: Spec, out_path: str, on_progress: Optional[ProgressCallback] = None
    ) -> str:
        total = round(spec.duration * FPS)
        if total < 1:
            raise RenderError(
                f"видео короче одного кадра: duration {spec.duration:g} с при {FPS} fps"
            )
        ffmpeg = _ffmpeg()
        _report(on_progress, 0, total)
        segments = _segments(spec)
        out = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        # Write next to out_path and rename at the end: out_path is either the
        # finished video or untouched, never a half-written file.
        part = f"{out}.{os.getpid()}.part"
        with tempfile.TemporaryDirectory(prefix="wibecode_") as tmp:
            cmd = [ffmpeg, "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
            filters = []
            for i, (frame, frames, fade) in enumerate(segments):
                png = os.path.join(tmp, f"{i:03d}.png")
                frame.save(png)
                seconds = frames / FPS
                cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.6f}", "-i", png]
                chain = f"[{i}:v]setsar=1,format=yuv420p"
                if fade and seconds > 4 * FADE:
                    chain += f",fade=t=in:d={FADE},fade=t=out:st={seconds - FADE:.6f}:d={FADE}"
                filters.append(f"{chain}[v{i}]")
            inputs = "".join(f"[v{i}]" for i in range(len(segments)))
            filters.append(f"{inputs}concat=n={len(segments)}:v=1:a=0[out]")
            cmd += [
                "-filter_complex", ";".join(filters), "-map", "[out]",
                "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-f", "mp4", part,
            ]  # fmt: skip
            try:
                _run_ffmpeg(cmd, os.path.join(tmp, "stderr.txt"), on_progress, total)
                # Last report while the video is still a temp file: a cancel or an
                # error here must leave out_path untouched.
                _report(on_progress, total, total)
                os.replace(part, out)
            finally:
                if os.path.exists(part):
                    os.remove(part)
        return out


def _run_ffmpeg(
    cmd: list[str], stderr_path: str, on_progress: Optional[ProgressCallback], total: int
) -> None:
    """Run FFmpeg, forwarding its "-progress" frame counter to on_progress."""
    with open(stderr_path, "w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
        try:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key == "frame" and value.isdigit():
                    # The last frame is reported once the file is final (below).
                    _report(on_progress, min(int(value), total - 1), total)
            proc.wait()
        finally:
            if proc.poll() is None:  # cancelled or callback raised
                proc.kill()
                proc.wait()
            proc.stdout.close()
        if proc.returncode != 0:
            err.seek(0)
            raise RenderError(f"FFmpeg завершился с ошибкой: {err.read().strip()[-500:]}")


RENDERERS: dict[str, Renderer] = {"2d": FFmpegRenderer()}


def get_renderer(mode: str) -> Renderer:
    if mode == "3d" and "3d" not in RENDERERS:
        # Imported lazily: the 3D backend reuses helpers from this module.
        from src.core.render3d import BlenderRenderer

        RENDERERS["3d"] = BlenderRenderer()
    try:
        return RENDERERS[mode]
    except KeyError:
        raise RenderError(f"нет рендерера для render_mode {mode!r}") from None


def render(spec: Spec, out_path: str, on_progress: Optional[ProgressCallback] = None) -> str:
    """Render spec with the backend for its render_mode."""
    return get_renderer(spec.render_mode).render(spec, out_path, on_progress)
