"""Standalone JSON worker for the installer-supplied Chatterbox Python runtime."""

import contextlib
import json
import os
import sys
import wave
from array import array
from pathlib import Path

if sys.platform == "win32":
    # PyInstaller's GUI DLL directory is inherited by child processes. It can
    # crash Chatterbox's native libraries; this standalone runtime owns its DLLs.
    import ctypes

    ctypes.windll.kernel32.SetDllDirectoryW(None)


def lazy_chinese(tokenizers):
    """The upstream Chinese-only segmenter otherwise downloads during every language's load."""
    converter = tokenizers.ChineseCangjieConverter

    class LazyConverter:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs, self.converter = args, kwargs, None

        def __call__(self, text):
            if self.converter is None:
                self.converter = converter(*self.args, **self.kwargs)
            return self.converter(text)

    tokenizers.ChineseCangjieConverter = LazyConverter


def run(request):
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from chatterbox.models.tokenizers import tokenizer

    lazy_chinese(tokenizer)
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    model = ChatterboxMultilingualTTS.from_local(Path(request["model_dir"]), device="cpu")
    builtin = model.conds
    output = Path(request["out_dir"])
    output.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, line in enumerate(request["lines"]):
        role, text = line["role"], line["text"]
        prompt = request["voices"].get(role)
        if prompt and not Path(prompt).is_file():
            raise FileNotFoundError(f"Файл голоса Chatterbox не найден: {prompt}")
        if not prompt:
            model.conds = builtin
        language = request.get("language") or (
            "ru" if any("а" <= ch.lower() <= "я" or ch in "ёЁ" for ch in text) else "en"
        )
        wav = model.generate(text, language_id=language, audio_prompt_path=prompt,
                             exaggeration={"narrator": 0.5, "robot": 0.3, "girl": 0.7}[role])
        samples = array("h", (round(max(-1.0, min(1.0, x)) * 32767)
                              for x in wav.squeeze(0).tolist()))
        path = output / f"voice_{index:03d}.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setparams((1, 2, model.sr, 0, "NONE", "not compressed"))
            stream.writeframes(samples.tobytes())
        clips.append({"path": str(path), "start": line["start"], "end": line["end"]})
    return clips


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        with contextlib.redirect_stdout(sys.stderr):
            clips = run(request)
        sys.stdout.buffer.write(json.dumps(clips, ensure_ascii=False).encode("utf-8"))
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
