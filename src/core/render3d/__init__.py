"""3D backend: Blender (Workbench) renders the studio, FFmpeg assembles the MP4.

Frames are rendered at 810x1440 and scaled to 1080x1920 at 30 fps. "say" lines
and gaps show the studio; text/image/chart scenes are flat full-frame inserts
made by the 2D renderer. Subtitles of "say" lines are overlaid by FFmpeg.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from src.core.render3d.subtitles import subtitle
from src.core.renderer import (
    FRAMES,
    HEIGHT,
    WIDTH,
    ProgressCallback,
    RenderError,
    ToolNotFoundError,
    _ffmpeg,
    _report,
    _run_ffmpeg,
)
from src.core.schema import SayScene, Spec
from src.core.styles import style_chain

FPS = 30
RENDER_WIDTH, RENDER_HEIGHT = 810, 1440
SCENE_SCRIPT = Path(__file__).with_name("blender_scene.py")
BLENDER_ENV = "WIBECODE_BLENDER"  # optional path to the blender executable


def _blender() -> str:
    exe = os.environ.get(BLENDER_ENV) or shutil.which("blender")
    if not exe:
        raise ToolNotFoundError(
            f"Blender не найден: установите Blender 4.2+ и добавьте его в PATH "
            f"или укажите путь в переменной {BLENDER_ENV}"
        )
    return exe


class _Progress:
    """Keeps done monotonic across stages and the final call for the very end."""

    def __init__(self, on_progress: Optional[ProgressCallback], total: int):
        self.on_progress, self.total, self.done = on_progress, total, 0

    def __call__(self, done: int, _total: int = 0) -> None:
        self.done = max(self.done, min(done, self.total - 1))
        _report(self.on_progress, self.done, self.total)


def _plan(spec: Spec, total: int):
    """Split the timeline into ("studio", first, last) and ("insert", scene, first, last)."""
    segments, cursor = [], 1
    for scene in sorted(spec.scenes, key=lambda s: s.start):
        first, last = round(scene.start * FPS) + 1, round(scene.end * FPS)
        if isinstance(scene, SayScene) or last < first:
            continue
        if first > cursor:
            segments.append(("studio", cursor, first - 1))
        segments.append(("insert", scene, first, last))
        cursor = last + 1
    if cursor <= total:
        segments.append(("studio", cursor, total))
    return segments


class BlenderRenderer:
    def render(
        self, spec: Spec, out_path: str, on_progress: Optional[ProgressCallback] = None
    ) -> str:
        total = round(spec.duration * FPS)
        if total < 1:
            raise RenderError(
                f"видео короче одного кадра: duration {spec.duration:g} с при {FPS} fps"
            )
        blender, ffmpeg = _blender(), _ffmpeg()
        progress = _Progress(on_progress, total)
        progress(0)
        segments = _plan(spec, total)
        lines = [
            (s, round(s.start * FPS) + 1, round(s.end * FPS))
            for s in spec.scenes
            if isinstance(s, SayScene)
        ]
        out = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        part = f"{out}.{os.getpid()}.part"
        with tempfile.TemporaryDirectory(prefix="wibecode3d_") as tmp:
            frames_dir = os.path.join(tmp, "frames")
            os.makedirs(frames_dir)
            studio = [f for seg in segments if seg[0] == "studio" for f in range(seg[1], seg[2] + 1)]
            done_before = total - len(studio)  # inserts cost nothing to "render"
            job = {
                "fps": FPS, "width": RENDER_WIDTH, "height": RENDER_HEIGHT,
                "frames_dir": frames_dir, "frames": studio,
                "lines": [{"who": s.who, "shot": s.shot, "first": a, "last": b} for s, a, b in lines],
            }  # fmt: skip
            job_path = os.path.join(tmp, "job.json")
            with open(job_path, "w", encoding="utf-8") as f:
                json.dump(job, f)
            if studio:
                self._run_blender(blender, job_path, tmp, lambda n: progress(done_before + n))
            cmd = self._assemble(ffmpeg, spec, segments, lines, frames_dir, tmp, part)
            try:
                _run_ffmpeg(cmd, os.path.join(tmp, "ffmpeg.txt"), progress, total)
                # Last report while the video is still a temp file: a cancel or an
                # error here must leave out_path untouched.
                _report(on_progress, total, total)
                os.replace(part, out)
            finally:
                if os.path.exists(part):
                    os.remove(part)
        return out

    @staticmethod
    def _run_blender(blender: str, job_path: str, tmp: str, on_frame) -> None:
        cmd = [blender, "-b", "--factory-startup", "-noaudio", "-P", str(SCENE_SCRIPT), "--", job_path]
        log_path = os.path.join(tmp, "blender.txt")
        with open(log_path, "w+", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True, errors="replace")
            rendered = 0
            try:
                for line in proc.stdout:
                    if line.startswith("WIBE_FRAME "):
                        rendered += 1
                        on_frame(rendered)
                proc.wait()
            finally:
                if proc.poll() is None:  # cancelled or callback raised
                    proc.kill()
                    proc.wait()
                proc.stdout.close()
            if proc.returncode != 0:
                log.seek(0)
                raise RenderError(f"Blender завершился с ошибкой: {log.read().strip()[-500:]}")

    @staticmethod
    def _assemble(ffmpeg, spec, segments, lines, frames_dir, tmp, part) -> list[str]:
        cmd = [ffmpeg, "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
        filters, labels, index = [], [], 0
        for seg in segments:
            if seg[0] == "studio":
                _, first, last = seg
                cmd += ["-framerate", str(FPS), "-start_number", str(first),
                        "-i", os.path.join(frames_dir, "f_%05d.png")]  # fmt: skip
                chain = f"[{index}:v]trim=end_frame={last - first + 1},setpts=PTS-STARTPTS,"
                chain += f"scale={WIDTH}:{HEIGHT}:flags=lanczos"
            else:
                _, scene, first, last = seg
                png = os.path.join(tmp, f"insert_{index}.png")
                FRAMES[type(scene)](scene).save(png)
                cmd += ["-loop", "1", "-framerate", str(FPS),
                        "-t", f"{(last - first + 1) / FPS:.6f}", "-i", png]  # fmt: skip
                chain = f"[{index}:v]scale={WIDTH}:{HEIGHT}"
            filters.append(f"{chain},setsar=1,format=yuv420p[s{index}]")
            labels.append(f"[s{index}]")
            index += 1
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[base]")
        current = "base"
        for i, (scene, first, last) in enumerate(lines):
            png = os.path.join(tmp, f"subtitle_{i}.png")
            subtitle(scene.text).save(png)
            cmd += ["-i", png]
            filters.append(
                f"[{current}][{index}:v]overlay=enable='between(n,{first - 1},{last - 1})'[o{i}]"
            )
            current = f"o{i}"
            index += 1
        styled = style_chain(spec.style, current, "styled")
        if styled:
            filters.append(styled)
            current = "styled"
        cmd += [
            "-filter_complex", ";".join(filters), "-map", f"[{current}]",
            "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-f", "mp4", part,
        ]  # fmt: skip
        return cmd
