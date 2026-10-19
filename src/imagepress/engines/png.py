"""PNG engine: libimagequant palette reduction + Oxipng recompression."""

from __future__ import annotations

import io
import typing as t

import imagequant
import oxipng
from PIL import Image

from ..errors import EncodeError
from ..result import EncodeAttempt
from .base import EncodeContext

_FILTERS_STANDARD = [
    oxipng.RowFilter.NoOp,
    oxipng.RowFilter.Sub,
    oxipng.RowFilter.Up,
    oxipng.RowFilter.Average,
    oxipng.RowFilter.Paeth,
]
_FILTERS_ALL = [
    *_FILTERS_STANDARD,
    oxipng.RowFilter.Bigrams,
    oxipng.RowFilter.BigEnt,
    oxipng.RowFilter.Brute,
]
_16BIT_MODES = {"I;16", "I;16B", "I;16L", "I", "F"}
_ALREADY_INDEXED = {"P", "L", "LA"}


def _optimize_png(data: bytes, ctx: EncodeContext) -> bytes:
    """Run Oxipng, preserving ICC and optional metadata when requested."""
    strip = (
        oxipng.StripChunks.none()
        if ctx.options.keep_metadata or ctx.icc
        else oxipng.StripChunks.safe()
    )
    common: dict[str, t.Any] = {
        "strip": strip,
        "optimize_alpha": False,
        "fix_errors": False,
    }
    effort = ctx.options.effort
    if effort == "fast":
        settings: dict[str, t.Any] = {
            "level": 2,
            "deflate": oxipng.Deflaters.libdeflater(9),
            "filter": _FILTERS_STANDARD,
        }
    elif effort == "max":
        settings = {
            "level": 6,
            "deflate": oxipng.Deflaters.zopfli(10),
            "filter": _FILTERS_ALL,
            "timeout": 30.0,
        }
    else:
        settings = {
            "level": 4,
            "deflate": oxipng.Deflaters.libdeflater(12),
            "filter": _FILTERS_STANDARD,
        }
    try:
        return bytes(
            oxipng.optimize_from_memory(data, **common, **settings)  # type: ignore[arg-type]
        )
    except Exception:
        # A failed lossless pass must not destroy an otherwise valid PNG.
        return data


def _save_png(image: Image.Image, ctx: EncodeContext) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, t.Any] = {"format": "PNG", "compress_level": 6}
    options.update(ctx.save_options())
    try:
        image.save(buffer, **options)
    except (OSError, ValueError, TypeError):
        options.pop("exif", None)
        buffer = io.BytesIO()
        try:
            image.save(buffer, **options)
        except (OSError, ValueError, TypeError) as exc:
            raise EncodeError(f"PNG encoding failed: {exc}") from exc
    return _optimize_png(buffer.getvalue(), ctx)


def _save_paletted(image: Image.Image, ctx: EncodeContext) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, t.Any] = {
        "format": "PNG",
        "compress_level": 6,
        "optimize": False,
    }
    options.update(ctx.save_options())
    try:
        image.save(buffer, **options)
    except (OSError, ValueError, TypeError):
        options.pop("exif", None)
        buffer = io.BytesIO()
        try:
            image.save(buffer, **options)
        except (OSError, ValueError, TypeError) as exc:
            raise EncodeError(f"PNG encoding failed: {exc}") from exc
    return _optimize_png(buffer.getvalue(), ctx)


def _encode_lossless(image: Image.Image, ctx: EncodeContext) -> bytes:
    return _save_png(image, ctx)


def _encode_palette(
    image: Image.Image,
    *,
    colors: int,
    dither: float,
    ctx: EncodeContext,
) -> tuple[bytes, int]:
    rgba = image.convert("RGBA")
    raw, palette = imagequant.quantize_raw_rgba_bytes(
        rgba.tobytes(),
        rgba.width,
        rgba.height,
        dithering_level=dither,
        max_colors=colors,
        min_quality=0,
        max_quality=100,
    )
    paletted = Image.frombytes("P", rgba.size, raw)
    paletted.putpalette(palette, rawmode="RGBA")
    # libimagequant may return a full palette even when fewer colours were
    # requested; count the indices actually used.
    used = len(set(raw))
    return _save_paletted(paletted, ctx), used


def _unique_colors_at_most(image: Image.Image, limit: int) -> int | None:
    """Count distinct colours, or return None when there are more than *limit*.

    ``Image.getcolors`` stops as soon as the limit is exceeded, so this stays
    fast and memory-bounded even for large photos.  NumPy is deliberately not
    used here; the PNG engine only needs Pillow.
    """
    colors = image.getcolors(maxcolors=limit)
    return None if colors is None else len(colors)


def _palette_sizes(max_colors: int, effort: str) -> list[int]:
    if effort == "fast":
        return [max_colors]
    sizes = [max_colors]
    for _ in range(3):
        candidate = sizes[-1] // 2
        if candidate < 4:
            break
        sizes.append(candidate)
    if effort == "max":
        sizes.extend([224, 192, 160, 96, 48, 24, 16])
    return sorted({size for size in sizes if 2 <= size <= max_colors}, reverse=True)


class PngEncoder:
    """Adaptive palette PNG encoder with a lossless fallback."""

    name = "PNG"
    supports_lossless = True
    install_hint = ""

    def available(self) -> bool:
        return True

    def encode(self, image: Image.Image, ctx: EncodeContext) -> EncodeAttempt:
        options = ctx.options

        if image.mode in _16BIT_MODES:
            return self._lossless(image, ctx, "16-bit PNG: lossless only")

        if options.quality == "auto" and image.mode in _ALREADY_INDEXED:
            return self._lossless(image, ctx, "indexed/greyscale PNG: lossless")

        if options.quality == "auto":
            unique = _unique_colors_at_most(image, options.max_colors)
            if unique is not None:
                return self._lossless(
                    image, ctx, f"only {unique} colours: lossless recompression"
                )

        if options.quality == "lossless":
            return self._lossless(image, ctx, "lossless PNG recompression")

        if options.quality_mode == "manual":
            assert options.quality_value is not None
            colors = max(
                2, min(256, round(options.max_colors * options.quality_value / 100))
            )
            data, used = _encode_palette(
                image, colors=colors, dither=options.dither, ctx=ctx
            )
            return EncodeAttempt(
                data=data,
                metrics=ctx.measure(data),
                quality=options.quality_value,
                palette_colors=used,
                note=f"PNG palette {used} colours (manual quality {options.quality_value})",
            )

        if not options.verify:
            data, used = _encode_palette(
                image, colors=options.max_colors, dither=options.dither, ctx=ctx
            )
            return EncodeAttempt(
                data=data,
                metrics=None,
                quality=options.max_colors,
                palette_colors=used,
                note=f"PNG palette {used} colours (verification disabled)",
            )

        attempts: list[EncodeAttempt] = []
        for colors in _palette_sizes(options.max_colors, options.effort):
            data, used = _encode_palette(
                image, colors=colors, dither=options.dither, ctx=ctx
            )
            attempt = EncodeAttempt(
                data=data,
                metrics=ctx.measure(data),
                quality=colors,
                palette_colors=used,
                note=f"PNG palette {used} colours, dither {options.dither:.2f}",
            )
            if ctx.accepts(attempt, palette=True):
                attempts.append(attempt)
            else:
                # Fewer colours cannot normally recover quality.  Stop early
                # so photos do not pay for every palette size.
                break

        if attempts:
            return min(attempts, key=lambda item: len(item.data))

        return self._lossless(
            image,
            ctx,
            "palette quantization missed the perceptual target; lossless PNG used",
        )

    def _lossless(
        self, image: Image.Image, ctx: EncodeContext, note: str
    ) -> EncodeAttempt:
        data = _encode_lossless(image, ctx)
        return EncodeAttempt(
            data=data,
            metrics=ctx.measure(data),
            quality="lossless",
            note=note,
        )
