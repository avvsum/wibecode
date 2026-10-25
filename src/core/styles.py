"""Post-processing looks (Spec.style) as FFmpeg filter chains on the final 1080x1920 video."""

from __future__ import annotations

from typing import Optional

WIDTH, HEIGHT = 1080, 1920  # final frame size of both renderers
PIXEL = 8  # pixel-art block size: 1080x1920 becomes a 135x240 grid

FILTERS = {
    "none": None,
    # Film: more contrast, muted colour, dark corners, moving grain.
    "cinematic": "eq=contrast=1.1:saturation=0.85,vignette=PI/5,noise=alls=6:allf=t",
    # Punchy colour and crisp edges: charts and big text.
    "vivid": "eq=contrast=1.05:saturation=1.4,unsharp=5:5:0.8",
    "bw": "hue=s=0,eq=contrast=1.15",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131,vignette=PI/6",
    # Pixel art: average each block, then blow it up with hard edges.
    "pixel": f"scale={WIDTH // PIXEL}:{HEIGHT // PIXEL}:flags=area,"
    f"scale={WIDTH}:{HEIGHT}:flags=neighbor",
    # VHS: split colour channels, washed curves, heavy grain, vignette.
    "retro": "rgbashift=rh=6:bh=-6,curves=preset=vintage,noise=alls=14:allf=t,vignette=PI/5",
    "warm": "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.06:bm=-0.06,eq=saturation=1.1",
    "cold": "colorbalance=rs=-0.08:bs=0.1:rm=-0.04:bm=0.08,eq=saturation=0.95",
    # Soft glow: blur a copy and screen it over the original.
    "dreamy": "format=gbrp,split[dream_a][dream_b];[dream_b]gblur=sigma=14[dream_c];"
    "[dream_a][dream_c]blend=all_mode=screen:all_opacity=0.35,eq=brightness=0.02",
}


def style_chain(style: str, src: str, dst: str) -> Optional[str]:
    """filter_complex fragment taking [src] to [dst] for style, or None for "none"."""
    chain = FILTERS[style]
    if chain is None:
        return None
    return f"[{src}]{chain},setsar=1,format=yuv420p[{dst}]"
