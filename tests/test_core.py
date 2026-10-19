from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from imagepress import (
    CompressionError,
    EncodeError,
    OptionError,
    OutputExistsError,
    compress_image,
    get_encoder,
    register_encoder,
)
from imagepress.metrics import compare


def _gradient(
    size: tuple[int, int] = (320, 240), *, alpha: bool = False
) -> Image.Image:
    width, height = size
    x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    r = (40 + 180 * x + 20 * np.sin(y * 9)).clip(0, 255)
    g = (30 + 170 * y + 30 * np.sin(x * 7)).clip(0, 255)
    b = (80 + 120 * (1 - x) * (0.4 + 0.6 * y)).clip(0, 255)
    rgb = np.stack(np.broadcast_arrays(r, g, b), axis=-1).astype(np.uint8)
    image = Image.fromarray(rgb, "RGB")
    if alpha:
        gradient_alpha = (
            255 * (0.35 + 0.65 * np.clip(1.2 - np.abs(x - 0.5) * 1.8, 0, 1))
        ).astype(np.uint8)
        gradient_alpha = np.broadcast_to(gradient_alpha, (height, width))
        image = image.convert("RGBA")
        image.putalpha(Image.fromarray(gradient_alpha, "L"))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (20, 20, 100, 70), fill=(250, 250, 250, 255) if alpha else (250, 250, 250)
    )
    draw.ellipse(
        (180, 110, 280, 210), fill=(20, 30, 120, 200) if alpha else (20, 30, 120)
    )
    return image


def test_png_auto_is_smaller_and_within_budget(tmp_path: Path) -> None:
    source = tmp_path / "gradient.png"
    _gradient().save(source, optimize=True)
    result = compress_image(source)
    assert result.output == tmp_path / "gradient.min.png"
    assert result.output.exists()
    assert result.output_format == "PNG"
    assert result.source_bytes > result.output_bytes
    assert result.target_met is True
    assert result.metrics is not None
    assert result.metrics.ssim >= 0.97
    assert result.metrics.delta_e_p95 <= 6.0
    assert result.palette_colors is None or result.palette_colors <= 256

    with Image.open(result.output) as output:
        assert output.mode in {"P", "RGB", "RGBA", "L", "LA"}


def test_alpha_survives_png_quantization(tmp_path: Path) -> None:
    source = tmp_path / "alpha.png"
    image = _gradient(alpha=True)
    image.save(source)
    result = compress_image(source)
    assert result.target_met is True
    assert result.metrics is not None
    assert result.metrics.alpha_psnr_db is not None
    with Image.open(result.output) as output:
        assert output.convert("RGBA").getchannel("A").getextrema() != (255, 255)


def test_jpeg_search_respects_quality_floor(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    _gradient((480, 320)).save(source, quality=95)
    result = compress_image(source)
    assert result.output_format == "JPEG"
    assert isinstance(result.quality, int)
    assert 60 <= result.quality <= 95
    assert result.target_met is True
    with Image.open(result.output) as output:
        assert output.format == "JPEG"
        assert output.info.get("progressive") in {1}


def test_manual_quality_and_conversion(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _gradient().save(source)
    result = compress_image(source, tmp_path / "out.webp", format="WEBP", quality=80)
    assert result.output_format == "WEBP"
    assert result.quality == 80
    assert result.output == tmp_path / "out.webp"
    with Image.open(result.output) as output:
        assert output.format == "WEBP"


def test_png_lossless_is_pixel_identical(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = _gradient()
    image.save(source)
    result = compress_image(source, quality="lossless")
    assert result.target_met is True
    with Image.open(source) as original, Image.open(result.output) as output:
        metrics = compare(original, output)
    assert metrics.ssim == 1.0
    assert metrics.psnr_db == float("inf")
    assert result.as_dict()["metrics"]["psnr_db"] is None
    assert result.note.startswith("lossless")


def test_lossless_jpeg_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    _gradient().save(source, quality=90)
    with pytest.raises(CompressionError, match="JPEG cannot"):
        compress_image(source, quality="lossless")


def test_same_format_never_grows(tmp_path: Path) -> None:
    source = tmp_path / "tiny.png"
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(source, optimize=True)
    result = compress_image(source)
    assert result.output_bytes <= result.source_bytes
    assert result.target_met is True


def test_overwrite_policy(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _gradient((96, 96)).save(source)
    output = tmp_path / "out.png"
    output.write_bytes(b"existing")

    with pytest.raises(OutputExistsError):
        compress_image(source, output)

    result = compress_image(source, output, overwrite=True)
    assert result.output == output
    assert output.stat().st_size == result.output_bytes


def test_output_equal_to_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _gradient((96, 96)).save(source)
    with pytest.raises(OptionError):
        compress_image(source, source, overwrite=True)


def test_verify_false_uses_conservative_default(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _gradient((128, 96)).save(source)
    result = compress_image(
        source,
        tmp_path / "out.jpg",
        format="JPEG",
        verify=False,
    )
    assert result.metrics is None
    assert result.target_met is None
    assert result.quality == 82


def test_animated_gif_preserves_frames_timing_and_loop(tmp_path: Path) -> None:
    frames = []
    for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
        frame = Image.new("RGB", (80, 60), color)
        ImageDraw.Draw(frame).text((5, 20), str(color), fill="white")
        frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=16))
    source = tmp_path / "anim.gif"
    frames[0].save(
        source,
        save_all=True,
        append_images=frames[1:],
        duration=[100, 200, 300],
        loop=3,
        disposal=2,
    )

    output = tmp_path / "anim.min.gif"
    result = compress_image(source, output)
    assert result.metrics is None
    assert result.target_met is None
    with Image.open(output) as gif:
        assert gif.n_frames == 3
        assert gif.info.get("loop") == 3
        durations = []
        for index in range(gif.n_frames):
            gif.seek(index)
            durations.append(gif.info.get("duration"))
        assert durations == [100, 200, 300]


def test_gif_manual_quality_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "static.gif"
    Image.new("P", (16, 16), 0).save(source)
    with pytest.raises(EncodeError):
        compress_image(source, tmp_path / "out.gif", quality=50)


def test_output_suffix_must_match_format(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _gradient((96, 96)).save(source)
    with pytest.raises(OptionError):
        compress_image(source, tmp_path / "out.webp", format="PNG")


def test_registry_can_replace_an_engine() -> None:
    class DummyEncoder:
        name = "PNG"
        supports_lossless = True
        install_hint = ""

        def available(self) -> bool:
            return True

        def encode(self, image, ctx):  # pragma: no cover - never called
            raise AssertionError("dummy encoder should not run")

    original = get_encoder("PNG")
    dummy = DummyEncoder()
    register_encoder(dummy, replace=True)
    try:
        assert get_encoder("PNG") is dummy
    finally:
        register_encoder(original, replace=True)
