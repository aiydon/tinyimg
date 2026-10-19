#!/usr/bin/env python3
"""Run the benchmark, write JSON/Markdown, and refresh the README section.

Usage:
    uv run python scripts/benchmark.py            # benchmark + previews + README
    uv run python scripts/benchmark.py --no-readme
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any

import click
from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from imagepress import (  # noqa: E402
    CompressionOptions,
    available_formats,
    compress_image,
)

SAMPLES = ROOT / "samples"
OUT = ROOT / "benchmark" / "out"
PREVIEWS = ROOT / "benchmark" / "previews"
RESULTS_JSON = ROOT / "benchmark" / "results.json"
RESULTS_MD = ROOT / "benchmark" / "results.md"
README = ROOT / "README.md"
START = "<!-- BENCHMARK:START -->"
END = "<!-- BENCHMARK:END -->"

# (crop box, difference amplification)
PREVIEW_SPECS = {
    "photo.jpg": ((440, 220, 840, 520), 8),
    "screenshot.png": ((300, 100, 700, 400), 12),
    "gradient.png": ((600, 180, 1000, 480), 12),
}
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _human(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MiB"
    return f"{size / 1024:.1f} KiB"


def _versions() -> str:
    packages = ["pillow", "numpy", "imagequant", "pyoxipng", "pillow-avif-plugin"]
    versions = []
    for package in packages:
        try:
            versions.append(f"{package} {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            versions.append(f"{package} not installed")
    return (
        f"Python {platform.python_version()} · "
        + " · ".join(versions)
        + " · effort=balanced"
    )


def _preview(name: str, result) -> Path:
    box, gain = PREVIEW_SPECS[name]
    with Image.open(SAMPLES / name) as opened:
        source = opened.convert("RGB")
    with Image.open(result.output) as opened:
        compressed = opened.convert("RGB")
    original_crop = source.crop(box)
    compressed_crop = compressed.crop(box)
    difference = ImageChops.difference(original_crop, compressed_crop)
    difference = difference.point(lambda value: min(255, value * gain))
    width, height = original_crop.size
    label_height = 28
    canvas = Image.new("RGB", (width * 3, height + label_height), "white")
    canvas.paste(original_crop, (0, 0))
    canvas.paste(compressed_crop, (width, 0))
    canvas.paste(difference, (width * 2, 0))
    draw = ImageDraw.Draw(canvas)
    draw.line([(width, 0), (width, height + label_height)], fill="#9ca3af", width=1)
    draw.line(
        [(width * 2, 0), (width * 2, height + label_height)],
        fill="#9ca3af",
        width=1,
    )
    try:
        font = ImageFont.truetype(str(FONT), 13)
    except OSError:
        font = ImageFont.load_default()
    quality_label = _quality_label_from_item(result.as_dict())
    labels = [
        "original · 100% crop",
        f"compressed (-{result.savings * 100:.0f}%) · {quality_label}",
        f"difference x{gain}",
    ]
    for index, label in enumerate(labels):
        draw.text((index * width + 8, height + 7), label, fill="#111111", font=font)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    slug = f"{Path(name).stem}-{Path(name).suffix.lstrip('.')}"
    path = PREVIEWS / f"{slug}.png"
    canvas.save(path, optimize=True)
    return path


def _markdown(results: list[dict[str, Any]], *, preview_prefix: str) -> str:
    lines: list[str] = []
    lines.append(f"环境：{_versions()}")
    lines.append("")
    lines.append(
        "| 样本 | 格式 | 原始 | 压缩后 | 节省 | SSIM | SSIM (2×) | PSNR | "
        "ΔE00 均值 | ΔE00 p95 | 编码 | 耗时 | 目标 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|")
    total_source = 0
    total_output = 0
    total_time = 0.0
    for item in results:
        metrics = item.get("metrics")
        total_source += int(item["source_bytes"])
        total_output += int(item["output_bytes"])
        total_time += float(item["elapsed_s"])
        if metrics is None:
            ssim = lowfreq = psnr = delta_mean = delta_p95 = "-"
            target = "n/a"
        else:
            ssim = f"{float(metrics['ssim']):.4f}"
            lowfreq = f"{float(metrics['ssim_lowfreq']):.4f}"
            psnr_value = metrics.get("psnr_db")
            psnr = "-" if psnr_value is None else f"{float(psnr_value):.1f} dB"
            delta_mean = f"{float(metrics['delta_e_mean']):.2f}"
            delta_p95 = f"{float(metrics['delta_e_p95']):.2f}"
            target = (
                "n/a"
                if item["target_met"] is None
                else ("通过" if item["target_met"] else "未通过")
            )
        lines.append(
            f"| `{Path(str(item['source'])).name}` | {item['output_format']} | "
            f"{_human(int(item['source_bytes']))} | {_human(int(item['output_bytes']))} | "
            f"{float(item['savings_pct']):.1f}% | {ssim} | "
            f"{lowfreq} | {psnr} | "
            f"{delta_mean} | {delta_p95} | "
            f"{_quality_label_from_item(item)} | {float(item['elapsed_s']):.2f}s | {target} |"
        )
    savings = 100.0 * (1.0 - total_output / total_source)
    lines.append(
        f"| **合计** |  | **{_human(total_source)}** | **{_human(total_output)}** | "
        f"**{savings:.1f}%** |  |  |  |  |  |  | **{total_time:.2f}s** |  |"
    )
    lines.append("")
    lines.append(
        "> SSIM 为全分辨率值（含抖动噪声），SSIM (2×) 为 2×2 盒式下采样后的值，"
        "PNG 调色板路径的验收使用的是后者。ΔE00 为 CIEDE2000，越小越好；"
        "p95 ≤ 6、均值 ≤ 2.5、SSIM (2×) ≥ 0.99、alpha PSNR ≥ 40 dB 为默认预算。"
    )
    lines.append("")
    lines.append("### 100% 局部对比")
    lines.append("")
    for name in ("photo.jpg", "screenshot.png", "gradient.png"):
        matching = [item for item in results if Path(str(item["source"])).name == name]
        if not matching:
            continue
        item = matching[0]
        slug = f"{Path(name).stem}-{Path(name).suffix.lstrip('.')}"
        preview = f"{preview_prefix}/{slug}.png"
        lines.append(
            f"**{name}** — 左：原图；中：压缩后；右：差异 ×{PREVIEW_SPECS[name][1]}。"
        )
        lines.append("")
        lines.append(f"![{name} comparison]({preview})")
        lines.append("")
    lines.append(
        "> 预览为 1:1 像素裁剪，避免缩放掩盖压缩痕迹。差异图经过放大，"
        "黑色表示完全相同；高倍放大后的噪声/dither 并不等于肉眼可见的差异。"
    )
    lines.append("")
    lines.append(
        "> `photo.jpg` 来自 Lorem Picsum / Unsplash；`photo.png`、`photo.webp`、"
        "`photo.avif` 由同一张照片派生；`screenshot.png`、`logo.png`、"
        "`gradient.png` 为本地生成。"
    )
    return "\n".join(lines)


def _quality_label_from_item(item: dict[str, Any]) -> str:
    output_format = str(item["output_format"])
    if output_format == "PNG":
        colors = item.get("palette_colors")
        return f"PNG {colors}c" if colors else "PNG lossless"
    if output_format == "GIF":
        return "GIF lossless"
    quality = item.get("quality")
    if quality in {None, "original", "lossless"}:
        return f"{output_format} {quality}"
    return f"{output_format} q{quality}"


@click.command()
@click.option("--no-readme", is_flag=True, help="Do not update README.md.")
def main(no_readme: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    results = []
    print(_versions())
    print()
    avif = available_formats().get("AVIF", False)
    for source in sorted(SAMPLES.iterdir()):
        if source.suffix.lower() == ".avif" and not avif:
            print(f"{source.name}: skipped (AVIF encoder unavailable)")
            continue
        if source.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".avif",
            ".gif",
            ".bmp",
            ".tiff",
        }:
            continue
        result = compress_image(
            source,
            OUT / source.name,
            options=CompressionOptions(overwrite=True),
        )
        item = result.as_dict()
        item["source"] = str(Path(str(item["source"])).relative_to(ROOT))
        item["output"] = str(Path(str(item["output"])).relative_to(ROOT))
        results.append(item)
        metrics = result.metrics
        quality = (
            f"SSIM {metrics.ssim:.4f}  dE95 {metrics.delta_e_p95:.2f}"
            if metrics is not None
            else "metrics n/a"
        )
        print(
            f"{source.name:16} {_human(result.source_bytes):>10} -> "
            f"{_human(result.output_bytes):>10}  {result.savings * 100:6.1f}%  "
            f"{quality}  {result.elapsed_s:.2f}s"
        )
        if source.name in PREVIEW_SPECS:
            _preview(source.name, result)

    RESULTS_JSON.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown = _markdown(results, preview_prefix="benchmark/previews")
    RESULTS_MD.write_text(
        _markdown(results, preview_prefix="previews") + "\n", encoding="utf-8"
    )

    if not no_readme and README.exists():
        text = README.read_text(encoding="utf-8")
        if START in text and END in text:
            before, rest = text.split(START, 1)
            _, after = rest.split(END, 1)
            README.write_text(
                f"{before}{START}\n{markdown}\n{END}{after}", encoding="utf-8"
            )
            print(f"\nupdated {README}")
        else:
            print(f"\n{START}/{END} markers not found; only wrote {RESULTS_MD}")

    total_source = sum(int(item["source_bytes"]) for item in results)
    total_output = sum(int(item["output_bytes"]) for item in results)
    print(
        f"\ntotal: {_human(total_source)} -> {_human(total_output)} "
        f"({100 * (1 - total_output / total_source):.1f}% smaller)"
    )
    print(f"wrote {RESULTS_JSON} and {RESULTS_MD}")


if __name__ == "__main__":
    main()
