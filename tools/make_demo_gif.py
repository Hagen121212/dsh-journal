#!/usr/bin/env python3
"""Compose docs/demo.gif from screenshots of the synthetic demo instance.

Frames are captured separately with a headless browser, for example:

    msedge --headless=new --hide-scrollbars --window-size=1280,760 \
      --screenshot=docs/frames/01-overview.png http://127.0.0.1:8766/

    python tools/make_demo_gif.py

The script cross-fades the frames and adds a short caption. It only ever uses
the synthetic demo database (tools/build_demo.py); never point it at real data.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "docs" / "frames"
OUTPUT = ROOT / "docs" / "demo.gif"

WIDTH = 960
HOLD_SECONDS = 1.7
FADE_SECONDS = 0.28
FPS = 9
PALETTE_COLORS = 128

CAPTIONS = {
    "01-overview": "概览：本周一句话 + 五维状态 + 最近会话",
    "02-timeline": "时间线：按周回看，点进任意一天",
    "03-growth": "成长：五维评分、证据与反例",
    "04-insights": "洞察：AI 起草，你确认或驳回",
    "05-reports": "报告：周报、基线、成长、L4 档案",
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc", "/System/Library/Fonts/PingFang.ttc"]:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _prepare(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGB")
    height = round(img.height * WIDTH / img.width)
    img = img.resize((WIDTH, height), Image.LANCZOS)

    caption = CAPTIONS.get(path.stem, path.stem)
    band = Image.new("RGB", (WIDTH, 44), (32, 36, 42))
    draw = ImageDraw.Draw(band)
    draw.text((18, 10), caption, font=_font(20), fill=(240, 238, 232))
    img = img.crop((0, 0, WIDTH, img.height - 44))
    canvas = Image.new("RGB", (WIDTH, img.height + 44), (32, 36, 42))
    canvas.paste(img, (0, 0))
    canvas.paste(band, (0, img.height))
    return canvas


def _to_gif_frame(img: Image.Image) -> Image.Image:
    return img.convert("P", palette=Image.ADAPTIVE, colors=PALETTE_COLORS)


def main(argv: list[str]) -> int:
    paths = sorted(FRAMES.glob("*.png"))
    if len(paths) < 2:
        print(f"need at least 2 frames in {FRAMES}", file=sys.stderr)
        return 2

    scenes = [_prepare(p) for p in paths]
    hold = max(1, round(HOLD_SECONDS * FPS))
    fade = max(1, round(FADE_SECONDS * FPS))

    frames: list[Image.Image] = []
    for index, scene in enumerate(scenes):
        frames.extend([_to_gif_frame(scene)] * hold)
        if index + 1 < len(scenes):
            following = scenes[index + 1]
            for step in range(1, fade + 1):
                blended = Image.blend(scene, following, step / (fade + 1))
                frames.append(_to_gif_frame(blended))

    duration = round(1000 / FPS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    print(f"wrote {OUTPUT}  frames={len(frames)}  {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
