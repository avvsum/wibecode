"""Spec -> MP4. Each scene becomes a still frame (Pillow), FFmpeg turns them into video."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.core.schema import ChartScene, ImageScene, Spec, TextScene

WIDTH, HEIGHT, FPS = 1080, 1920, 30
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


class Renderer(Protocol):
    def render(self, spec: Spec, out_path: str) -> str:
        """Write spec as a video to out_path and return the path."""
        ...


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


def _chart_frame(scene: ChartScene) -> Image.Image:
    img = _blank()
    draw = ImageDraw.Draw(img)
    left, right, top, bottom = 140, WIDTH - 80, 460, HEIGHT - 460
    xs = [x for x, _ in scene.data]
    ys = [y for _, y in scene.data]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(min(ys), 0), max(ys)
    if x1 == x0:
        x0, x1 = x0 - 1, x1 + 1
    if y1 == y0:
        y1 = y0 + 1

    def px(x: float, y: float) -> tuple[float, float]:
        return (
            left + (x - x0) / (x1 - x0) * (right - left),
            bottom - (y - y0) / (y1 - y0) * (bottom - top),
        )

    label = _font(40)
    for k in range(5):
        y = y0 + (y1 - y0) * k / 4
        _, py = px(x0, y)
        draw.line([(left, py), (right, py)], fill=GRID, width=2)
        draw.text((left - 20, py), f"{y:g}", font=label, fill=FG, anchor="rm")
    for x, _ in scene.data:
        draw.text((px(x, y0)[0], bottom + 30), f"{x:g}", font=label, fill=FG, anchor="mt")
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
        raise RenderError("FFmpeg не найден: установите его и добавьте в PATH")
    return exe


class FFmpegRenderer:
    """2D renderer: still frames per scene, fades, H.264 MP4 1080x1920 @ 30 fps."""

    def render(self, spec: Spec, out_path: str) -> str:
        ffmpeg = _ffmpeg()
        segments = _segments(spec)
        out = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="wibecode_") as tmp:
            cmd = [ffmpeg, "-y", "-v", "error"]
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
                "-movflags", "+faststart", out,
            ]  # fmt: skip
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RenderError(f"FFmpeg завершился с ошибкой: {proc.stderr.strip()[-500:]}")
        return out


class Stub3DRenderer:
    """Placeholder until the 3D backend (Blender / moderngl / Manim) is chosen."""

    def render(self, spec: Spec, out_path: str) -> str:
        raise NotImplementedError("3D not implemented yet")


RENDERERS: dict[str, Renderer] = {"2d": FFmpegRenderer(), "3d": Stub3DRenderer()}


def get_renderer(mode: str) -> Renderer:
    try:
        return RENDERERS[mode]
    except KeyError:
        raise RenderError(f"нет рендерера для render_mode {mode!r}") from None


def render(spec: Spec, out_path: str) -> str:
    """Render spec with the backend for its render_mode."""
    return get_renderer(spec.render_mode).render(spec, out_path)
