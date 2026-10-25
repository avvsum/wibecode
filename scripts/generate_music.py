"""Rebuild the original CC0 demo music with stdlib synthesis and FFmpeg.

No samples, existing songs, external Python packages, or network access are used.
Run from the repository: python scripts/generate_music.py
"""

from __future__ import annotations

import argparse
from array import array
import math
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import wave

RATE = 22050
ROOT = Path(__file__).resolve().parents[1]
# Four bars / sixteen beats: every demo lasts between eight and twelve seconds.
MOODS = {
    "calm": (80, 60, "major", "Cloud Garden"),
    "upbeat": (120, 62, "major", "Small Adventures"),
    "epic": (100, 57, "minor", "New Horizon"),
    "lofi": (88, 60, "major", "Window Light"),
    "retro": (116, 60, "minor", "Pixel Steps"),
    "tense": (96, 57, "minor", "Quiet Mystery"),
    "happy": (112, 65, "major", "Sunny Walk"),
}
MELODY = (
    (0, 2, 4, None, 7, 4, 2, None),
    (4, None, 7, 9, 7, None, 4, 2),
    (2, 4, None, 7, 4, 2, 0, None),
    (4, 2, 0, None, -3, 0, 2, None),
)


def compose(mood: str) -> tuple[array, float]:
    bpm, key, mode, _title = MOODS[mood]
    beat = 60 / bpm
    count = round(16 * beat * RATE)
    left, right = [0.0] * count, [0.0] * count
    rng = random.Random(20261025 + list(MOODS).index(mood))

    def note(at: float, duration: float, midi: int, gain: float,
             voice: str = "keys", pan: float = 0.0) -> None:
        frequency = 440 * 2 ** ((midi - 69) / 12)
        start, length = round(at * RATE), round(duration * RATE)
        for i in range(length):
            t = i / RATE
            attack = min(1.0, t / (0.08 if voice == "pad" else 0.012))
            release = min(1.0, (length - i) / (RATE * 0.055))
            phase = math.tau * frequency * t
            if voice == "pad":
                tone = math.sin(phase) + 0.14 * math.sin(phase * 2)
                envelope = attack * release * math.exp(-0.6 * t)
            elif voice == "bass":
                tone = math.sin(phase) + 0.16 * math.sin(phase * 2)
                envelope = attack * release * math.exp(-2.4 * t)
            elif voice == "chip":
                tone = (math.sin(phase) + 0.22 * math.sin(phase * 3)
                        + 0.08 * math.sin(phase * 5))
                envelope = attack * release * math.exp(-4.3 * t)
            else:
                tone = (math.sin(phase) + 0.22 * math.sin(phase * 2)
                        + 0.06 * math.sin(phase * 3))
                envelope = attack * release * math.exp(-3.1 * t)
            value = gain * tone * envelope
            # Circular accumulation carries the final note tail into the start.
            index = (start + i) % count
            left[index] += value * (1 - pan) * 0.5
            right[index] += value * (1 + pan) * 0.5

    def drum(at: float, kind: str, gain: float) -> None:
        duration = 0.22 if kind == "kick" else 0.12
        start = round(at * RATE)
        previous = 0.0
        for i in range(round(duration * RATE)):
            t = i / RATE
            noise = rng.uniform(-1, 1)
            if kind == "kick":
                value = math.sin(math.tau * (48 * t + 2.5 * (1 - math.exp(-25 * t))))
                value *= math.exp(-24 * t) * min(1, t / 0.003)
            else:
                value = (noise - previous) * math.exp(-45 * t)
                previous = noise
            index = (start + i) % count
            left[index] += gain * value * 0.5
            right[index] += gain * value * 0.5

    roots = (0, 5, 9, 7) if mode == "major" else (0, 5, 8, 7)
    for bar, root in enumerate(roots):
        start = bar * 4 * beat
        third = 4 if mode == "major" and root != 9 else 3
        if mode == "minor":
            third = 4 if root == 8 else 3
        seventh = 11 if (mode == "major" and root in (0, 5)) or (mode == "minor" and root == 8) else 10
        chord = (root, root + third, root + 7, root + seventh)
        if mood == "tense":
            chord = chord[:3]
        for j, interval in enumerate(chord):
            note(start, beat * 3.9, key + interval, 0.065,
                 "pad", (j - 1.5) * 0.22)
        for step in (0, 2):
            note(start + step * beat, beat * 1.4, key + root - 24,
                 0.19 if mood in {"epic", "upbeat"} else 0.13, "bass")
        pattern = MELODY[bar]
        for step, interval in enumerate(pattern):
            if interval is None or (mood == "calm" and step % 2):
                continue
            if mode == "minor" and interval in (4, 9):
                interval -= 1
            swing = 0.07 * beat if mood == "lofi" and step % 2 else 0
            note(start + step * beat / 2 + swing, beat * 0.85,
                 key + 12 + interval, 0.105 if mood != "tense" else 0.06,
                 "chip" if mood == "retro" else "keys", 0.18)
        if mood not in {"calm", "tense"}:
            for step in (0, 2):
                drum(start + step * beat, "kick", 0.15)
            for step in (1, 3):
                drum(start + step * beat, "hat", 0.035)
            for step in range(8):
                drum(start + step * beat / 2, "hat", 0.012)
        elif mood == "tense":
            for step in (0, 1.5, 3):
                note(start + step * beat, beat * 0.4, key - 12, 0.10, "bass")

    peak = max(max(abs(v) for v in left), max(abs(v) for v in right), 0.01)
    scale = 0.65 * 32767 / peak
    samples = array("h")
    for lvalue, rvalue in zip(left, right):
        samples.extend((round(lvalue * scale), round(rvalue * scale)))
    return samples, count / RATE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "music")
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error("FFmpeg is required on PATH or via --ffmpeg")
    with tempfile.TemporaryDirectory(prefix="shorts-music-") as tmp:
        for mood, (_bpm, _key, _mode, title) in MOODS.items():
            samples, duration = compose(mood)
            wav = Path(tmp) / (mood + ".wav")
            with wave.open(str(wav), "wb") as stream:
                stream.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
                stream.writeframes(samples.tobytes())
            folder = args.output / mood
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / "shorts-original.ogg"
            subprocess.run([
                str(args.ffmpeg), "-y", "-v", "error", "-i", str(wav),
                "-c:a", "libvorbis", "-q:a", "2", "-map_metadata", "-1",
                "-metadata", f"title={title}", "-metadata", "artist=ShortsStudio",
                "-metadata", "license=CC0-1.0", str(output),
            ], check=True)
            print(f"{mood}: {duration:.2f} s, {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
