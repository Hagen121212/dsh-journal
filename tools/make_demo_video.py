#!/usr/bin/env python3
"""Render a short silent demo video from the synthetic demo screenshots.

    python tools/make_demo_video.py --out ../dsh-journal-demo.mp4

Frames come from a headless browser pointed at the demo instance created by
``tools/build_demo.py`` (synthetic data only). The script bakes captions with
Pillow and hands the cross-fade to ffmpeg, which must be on PATH or passed
with ``--ffmpeg``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FRAMES_DIR = ROOT / "docs" / "frames-hd"
WORK_DIR = ROOT / "docs" / "video-build"

W, H = 1920, 1080
FADE = 0.6
DURATIONS = [3.0, 4.2, 4.0, 4.6, 4.2, 3.6, 2.8]  # title + 5 pages + end card

CAPTIONS = {
    "01-overview": "概览 · 本周一句话、五维状态、最近会话",
    "02-timeline": "时间线 · 按周回看，点进任意一天",
    "03-growth": "成长 · 五维评分、证据与反例",
    "04-insights": "洞察 · AI 起草，你确认或驳回",
    "05-reports": "报告 · 周报、基线、成长、L4 档案",
}

INK = (32, 36, 42)
PAPER = (244, 242, 236)
MUTED = (107, 113, 105)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    raise SystemExit("找不到中文字体（msyh.ttc / PingFang）")


def _centered(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((W - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)


def _title_card() -> Image.Image:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    _centered(draw, 360, "思维年轮", _font(104, bold=True), INK)
    _centered(draw, 500, "DeepSeek Journal", _font(44), MUTED)
    _centered(draw, 610, "把 DSH 的本地会话，变成可回看的证据链", _font(38), INK)
    _centered(draw, 690, "会话卡 · 周报 · 双周成长 · L4 确认", _font(30), MUTED)
    _centered(draw, 960, "合成演示数据 · 不含任何真实聊天", _font(24), (138, 143, 134))
    return img


def _end_card() -> Image.Image:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    _centered(draw, 420, "github.com/Hagen121212/dsh-journal", _font(54, bold=True), INK)
    _centered(draw, 520, "github.com/Hagen121212/dsh-journal-panel", _font(34), MUTED)
    _centered(draw, 640, "MIT · 本地优先 · 非官方", _font(30), MUTED)
    return img


def _captioned(path: Path) -> Image.Image:
    """Page screenshot on top, opaque caption bar underneath (no overlay)."""
    band_h = 78
    page = Image.open(path).convert("RGB").resize((W, H), Image.LANCZOS)
    page = page.crop((0, 0, W, H - band_h))
    canvas = Image.new("RGB", (W, H), (24, 27, 32))
    canvas.paste(page, (0, 0))
    draw = ImageDraw.Draw(canvas)
    caption = CAPTIONS.get(path.stem, path.stem)
    draw.text((56, H - band_h + 22), caption, font=_font(30), fill=(245, 243, 238))
    return canvas


def _find_ffmpeg(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in Path(ROOT.parent / ".tools").glob("ffmpeg/**/bin/ffmpeg.exe"):
        return str(candidate)
    raise SystemExit("找不到 ffmpeg，用 --ffmpeg 指定路径")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="output .mp4 path")
    parser.add_argument("--ffmpeg", default=None)
    args = parser.parse_args(argv)

    ffmpeg = _find_ffmpeg(args.ffmpeg)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    pages = sorted(FRAMES_DIR.glob("*.png"))
    if len(pages) != 5:
        print(f"expected 5 frames in {FRAMES_DIR}, found {len(pages)}", file=sys.stderr)
        return 2

    scenes = [_title_card()] + [_captioned(p) for p in pages] + [_end_card()]
    sources = []
    for index, scene in enumerate(scenes):
        path = WORK_DIR / f"scene-{index:02d}.png"
        scene.save(path)
        sources.append(path)

    filters = "".join(
        f"[{i}:v]scale={W}:{H},setsar=1,format=yuv420p[v{i}];" for i in range(len(sources))
    )
    chain = "[v0]"
    acc = DURATIONS[0]
    for i in range(1, len(sources)):
        offset = acc - FADE
        label = f"[x{i}]"
        filters += f"{chain}[v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}{label};"
        chain = label
        acc = acc + DURATIONS[i] - FADE

    cmd = [ffmpeg, "-y"]
    for path, duration in zip(sources, DURATIONS):
        cmd += ["-loop", "1", "-t", str(duration), "-i", str(path)]
    cmd += [
        "-filter_complex", filters.rstrip(";"),
        "-map", chain,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart",
        args.out,
    ]
    print("running:", " ".join(cmd[:8]), "...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr[-3000:], file=sys.stderr)
        return proc.returncode

    size = Path(args.out).stat().st_size / 1024 / 1024
    print(f"wrote {args.out}  {size:.1f} MB  ~{acc:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
