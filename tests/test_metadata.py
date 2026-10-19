from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageCms

from tinyimg import compress_image


def test_exif_orientation_is_applied_and_reset(tmp_path: Path) -> None:
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise for display.
    Image.new("RGB", (40, 20), "red").save(source, quality=95, exif=exif)

    output = tmp_path / "rotated.min.jpg"
    result = compress_image(source, output, keep_metadata=True)
    assert result.output_format == "JPEG"
    with Image.open(output) as image:
        assert image.size == (20, 40)
        assert image.getexif().get(274) == 1


def test_metadata_is_stripped_by_default(tmp_path: Path) -> None:
    source = tmp_path / "exif.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "artist"
    Image.new("RGB", (40, 20), "blue").save(source, quality=95, exif=exif)

    output = tmp_path / "exif.min.jpg"
    compress_image(source, output)
    with Image.open(output) as image:
        assert image.size == (20, 40)
        assert not image.info.get("exif")


def test_icc_profile_is_preserved_by_default(tmp_path: Path) -> None:
    source = tmp_path / "icc.png"
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (48, 32), "green").save(source, icc_profile=icc)

    output = tmp_path / "icc.min.png"
    compress_image(source, output)
    with Image.open(output) as image:
        assert image.info.get("icc_profile") == icc


def test_measure_applies_exif_orientation(tmp_path: Path) -> None:
    from tinyimg import CompressionOptions
    from tinyimg.engines.base import EncodeContext

    source = tmp_path / "rotated.png"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), "red").save(source, exif=exif)
    raw = source.read_bytes()

    reference = Image.new("RGB", (20, 40), "red")
    ctx = EncodeContext(
        options=CompressionOptions(),
        reference=reference,
        original=raw,
        source_format="PNG",
    )
    metrics = ctx.measure(raw)
    assert metrics is not None
    assert metrics.ssim == 1.0
    assert metrics.delta_e_p95 == 0.0
