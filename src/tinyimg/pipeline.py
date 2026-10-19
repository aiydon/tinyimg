"""Decode -> choose engine -> encode -> verify -> write.

The pipeline owns filesystem policy (naming, overwrite, metadata) and knows
nothing about codec internals.  Codecs implement :class:`tinyimg.Encoder`.
"""

from __future__ import annotations

import io
import pathlib as p
import time
import typing as t
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from .engines import EncodeContext, get_encoder
from .errors import (
    DecodeError,
    EncodeError,
    OptionError,
    OutputExistsError,
    TinyImgError,
    UnsupportedFormatError,
)
from .formats import (
    FORMATS,
    INPUT_SUFFIXES,
    format_from_suffix,
    normalize_format,
)
from .options import CompressionOptions, OptionsLike, resolve_options
from .result import BatchFailure, BatchReport, CompressionResult
from .type import PathLike

_PNG_PASSTHROUGH = {
    "P",
    "L",
    "LA",
    "RGB",
    "RGBA",
    "I;16",
    "I;16B",
    "I;16L",
}


class _Loaded(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    image: Image.Image
    format: str
    animated: bool
    exif: bytes | None
    icc: bytes | None
    raw: bytes


def _load(path: p.Path) -> _Loaded:
    try:
        raw = path.read_bytes()
    except OSError:
        raise
    if not raw:
        raise DecodeError(f"source file is empty: {path}")

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            detected = (opened.format or "").upper()
            animated = bool(getattr(opened, "is_animated", False))
            exif = opened.info.get("exif")
            icc = opened.info.get("icc_profile")
            opened.load()
            # ``in_place=False`` guarantees an independent copy, so we do not
            # need a second full-image copy after applying orientation.
            normalized = ImageOps.exif_transpose(opened, in_place=False)
            normalized.load()
    except UnidentifiedImageError as exc:
        raise DecodeError(f"cannot decode {path}: {exc}") from exc
    except OSError as exc:
        raise DecodeError(f"cannot decode {path}: {exc}") from exc

    source_format = normalize_format(detected or path.suffix)
    return _Loaded(
        image=normalized,
        format=source_format,
        animated=animated,
        exif=exif,
        icc=icc,
        raw=raw,
    )


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA", "PA", "RGBa", "La"}:
        return True
    if image.mode == "P":
        return "transparency" in image.info
    return False


def _flatten(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (*background, 255))
    return Image.alpha_composite(canvas, rgba).convert("RGB")


def _prepare_base(
    image: Image.Image,
    output_format: str,
    background: tuple[int, int, int],
) -> tuple[Image.Image, bool]:
    """Convert the decoded image into the representation an engine expects."""
    if output_format == "JPEG":
        if _has_alpha(image):
            return _flatten(image, background), True
        if image.mode == "L":
            return image.copy(), False
        return image.convert("RGB"), False

    if output_format in {"WEBP", "AVIF"}:
        mode = "RGBA" if _has_alpha(image) else "RGB"
        return image.convert(mode), False

    if output_format == "PNG":
        if image.mode in _PNG_PASSTHROUGH:
            return image.copy(), False
        mode = "RGBA" if _has_alpha(image) else "RGB"
        return image.convert(mode), False

    if output_format == "GIF":
        return image.copy(), False

    raise UnsupportedFormatError(f"cannot prepare pixels for {output_format}")


def _safe_icc(
    source_mode: str,
    base_mode: str,
    icc: bytes | None,
) -> bytes | None:
    if not icc:
        return None
    if source_mode in {"CMYK", "LAB", "HSV", "YCbCr"} and base_mode in {
        "RGB",
        "RGBA",
    }:
        # A CMYK profile cannot describe RGB pixels.
        return None
    if source_mode in {"L", "LA", "I;16", "I;16B", "I;16L"} and base_mode in {
        "RGB",
        "RGBA",
    }:
        return None
    return icc


def _clean_exif(exif: bytes | None) -> bytes | None:
    if not exif:
        return None
    try:
        parsed = Image.Exif()
        parsed.load(exif)
        if 274 in parsed:  # Orientation
            parsed[274] = 1
        return parsed.tobytes()
    except Exception:
        return exif


def _resolve_output_format(
    source_format: str,
    requested: str | None,
    output: p.Path | None,
    *,
    output_is_dir: bool,
) -> str:
    suffix_format = None
    if output is not None and not output_is_dir:
        suffix_format = format_from_suffix(output)
        if output.suffix and suffix_format is None and requested is None:
            raise UnsupportedFormatError(
                f"cannot infer an output format from suffix {output.suffix!r}; "
                "pass format=..."
            )

    if requested is not None:
        if suffix_format is not None and suffix_format != requested:
            raise OptionError(
                f"output suffix implies {suffix_format}, but format={requested}"
            )
        resolved = requested
    elif suffix_format is not None:
        resolved = suffix_format
    elif FORMATS[source_format].can_encode:
        resolved = source_format
    elif source_format in {"BMP", "TIFF"}:
        resolved = "PNG"
    else:
        raise UnsupportedFormatError(f"no output format for {source_format}")

    if resolved not in FORMATS or not FORMATS[resolved].can_encode:
        raise UnsupportedFormatError(
            f"{resolved} is not an output format; choose from "
            f"{', '.join(name for name, spec in FORMATS.items() if spec.can_encode)}"
        )
    return resolved


def _output_path(
    source: p.Path,
    output: p.Path | None,
    output_format: str,
    *,
    output_is_dir: bool,
) -> p.Path:
    suffix = FORMATS[output_format].suffix
    name = f"{source.stem}.min{suffix}"
    if output is None:
        return source.with_name(name)
    if output_is_dir:
        return output / name
    return output


def _check_output(
    output: p.Path,
    source: p.Path,
    options: CompressionOptions,
) -> None:
    if output.resolve() == source.resolve():
        raise OptionError("output path is the source image; refusing to overwrite it")
    if output.exists() and not options.overwrite:
        raise OutputExistsError(
            f"output already exists: {output} (pass overwrite=True to replace it)"
        )


def compress_image(
    source: PathLike,
    output: PathLike | None = None,
    *,
    options: OptionsLike = None,
    **overrides: t.Any,
) -> CompressionResult:
    """Compress one image while keeping the result visually indistinguishable.

    ``options`` accepts a :class:`CompressionOptions` object, a mapping (for
    JSON/config-driven callers), or ``None``.  Keyword arguments are forwarded
    to :class:`CompressionOptions`, so both styles work::

        compress_image("in.png", "out.png", quality="auto")
        opts = CompressionOptions(quality=85, budget=Budget(ssim=0.99))
        compress_image("in.png", "out.png", options=opts)

    The output is never the source path, and an existing output is only
    replaced when ``overwrite=True`` (or ``options.overwrite=True``).

    Raises
    ------
    FileNotFoundError / IsADirectoryError
        The source does not exist or is not a regular file.
    TinyImgError
        Invalid options, unsupported format, decode/encode failure, or an
        existing output when ``overwrite=False``.
    OSError
        Filesystem read/write failures.
    """
    opts = resolve_options(options, overrides)
    started = time.perf_counter()

    source_path = p.Path(source)
    if source_path.is_dir():
        raise IsADirectoryError(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    loaded = _load(source_path)
    base: Image.Image | None = None
    try:
        requested_path = p.Path(output) if output is not None else None
        if (
            requested_path is not None
            and requested_path.exists()
            and not requested_path.is_dir()
            and requested_path.suffix == ""
        ):
            raise OptionError(
                "output is a file without a suffix; pass a directory or a "
                "file with an image suffix"
            )
        output_is_dir = bool(
            requested_path is not None
            and (requested_path.is_dir() or requested_path.suffix == "")
        )

        output_format = _resolve_output_format(
            loaded.format,
            opts.format,
            requested_path,
            output_is_dir=output_is_dir,
        )
        if loaded.animated and not (loaded.format == "GIF" and output_format == "GIF"):
            raise UnsupportedFormatError(
                "animated images are only supported as GIF -> GIF lossless optimization"
            )

        encoder = get_encoder(output_format)
        if opts.quality == "lossless" and not encoder.supports_lossless:
            raise EncodeError(
                f"{output_format} cannot be encoded losslessly; use PNG or WebP"
            )

        output_path = _output_path(
            source_path,
            requested_path,
            output_format,
            output_is_dir=output_is_dir,
        )
        _check_output(output_path, source_path, opts)

        base, flattened = _prepare_base(loaded.image, output_format, opts.background)
        icc = loaded.icc
        if base.mode != loaded.image.mode:
            icc = _safe_icc(loaded.image.mode, base.mode, icc)
        ctx = EncodeContext(
            options=opts,
            reference=base,
            original=loaded.raw,
            source_format=loaded.format,
            icc=icc,
            exif=_clean_exif(loaded.exif),
            animated=loaded.animated,
        )

        attempt = encoder.encode(base, ctx)
        notes: list[str] = []
        if flattened:
            notes.append(
                "alpha flattened onto "
                f"#{opts.background[0]:02X}{opts.background[1]:02X}"
                f"{opts.background[2]:02X}"
            )
        if attempt.note:
            notes.append(attempt.note)

        final_bytes = attempt.data
        metrics = attempt.metrics
        quality = attempt.quality
        palette_colors = attempt.palette_colors
        target_met = (
            None
            if metrics is None
            else opts.budget.accepts(metrics, palette=palette_colors is not None)
        )

        # Never write a larger file when the format did not change.  The
        # source may already be better compressed than a fresh encode.
        if output_format == loaded.format and len(final_bytes) >= len(loaded.raw):
            final_bytes = loaded.raw
            quality = "original"
            palette_colors = None
            notes = [
                note for note in notes if "perceptual target not reached" not in note
            ]
            notes.append("original kept: re-encode was not smaller")
            metrics = ctx.measure(final_bytes)
            target_met = None if metrics is None else opts.budget.accepts(metrics)

        if output_format != loaded.format and len(final_bytes) > len(loaded.raw):
            notes.append("format conversion increased size")
        if opts.quality_mode == "manual" and target_met is False:
            notes.append("manual quality is outside the perceptual target")
        if opts.quality == "lossless" and loaded.format != output_format:
            notes.append("lossless re-encode of decoded pixels")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(final_bytes)

        return CompressionResult(
            source=source_path,
            output=output_path,
            source_format=loaded.format,
            output_format=output_format,
            encoder=encoder.name,
            source_bytes=len(loaded.raw),
            output_bytes=len(final_bytes),
            elapsed_s=time.perf_counter() - started,
            metrics=metrics,
            target_met=target_met,
            quality=quality,
            palette_colors=palette_colors,
            note="; ".join(dict.fromkeys(note for note in notes if note)),
        )
    finally:
        if base is not None:
            base.close()
        loaded.image.close()


def _collect_files(
    sources: Iterable[PathLike],
    *,
    recursive: bool,
) -> list[p.Path]:
    if isinstance(sources, (str, p.Path)):
        sources = [sources]

    files: list[p.Path] = []
    seen: set[p.Path] = set()

    def add(path: p.Path) -> None:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            files.append(path)

    for item in sources:
        path = p.Path(item)
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(path.glob(pattern)):
                if child.is_file() and child.suffix.lower() in INPUT_SUFFIXES:
                    add(child)
        else:
            add(path)
    return files


def _planned_output_format(source: p.Path, options: CompressionOptions) -> str | None:
    """Best-effort output format for collision detection (no decoding)."""
    if options.format is not None:
        return options.format
    fmt = format_from_suffix(source)
    if fmt is None:
        return None
    return "PNG" if fmt in {"BMP", "TIFF"} else fmt


def _check_batch_outputs(
    files: list[p.Path],
    output: p.Path | None,
    options: CompressionOptions,
) -> None:
    if output is None or len(files) <= 1:
        return
    if output.exists() and not output.is_dir():
        raise OptionError("with multiple inputs, output must be a directory")
    if not output.is_dir() and output.suffix:
        raise OptionError("with multiple inputs, output must be a directory")

    seen: dict[tuple[str, str], p.Path] = {}
    for source in files:
        fmt = _planned_output_format(source, options)
        if fmt is None:
            continue
        key = (source.stem, fmt)
        previous = seen.get(key)
        if previous is not None:
            raise OptionError(
                "multiple inputs would write the same output name: "
                f"{previous} and {source}; rename one or use separate output "
                "directories"
            )
        seen[key] = source


def compress_many(
    sources: Iterable[PathLike],
    output: PathLike | None = None,
    *,
    options: OptionsLike = None,
    recursive: bool = False,
    workers: int = 1,
    on_result: Callable[[CompressionResult], None] | None = None,
    on_error: Callable[[p.Path, Exception], None] | None = None,
    **overrides: t.Any,
) -> BatchReport:
    """Compress a list of files and/or directories.

    Failures are collected per input instead of aborting the batch.  Results
    and failures preserve input order; callbacks fire as each item completes
    (from worker threads when ``workers > 1``, so they must be thread-safe).
    ``workers=1`` is the safe library default; the CLI enables parallelism.
    """
    opts = resolve_options(options, overrides)
    started = time.perf_counter()
    files = _collect_files(sources, recursive=recursive)

    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise OptionError("workers must be an integer >= 1")

    _check_batch_outputs(files, p.Path(output) if output is not None else None, opts)

    outcomes: list[tuple[int, CompressionResult | None, Exception | None]] = []

    def record(
        index: int,
        source: p.Path,
        result: CompressionResult | None,
        error: Exception | None,
    ) -> None:
        outcomes.append((index, result, error))
        if result is not None and on_result is not None:
            on_result(result)
        if error is not None and on_error is not None:
            on_error(source, error)

    def run(index: int, source: p.Path) -> None:
        try:
            result = compress_image(source, output, options=opts)
        except (TinyImgError, OSError) as exc:
            record(index, source, None, exc)
        else:
            record(index, source, result, None)

    if workers == 1 or len(files) <= 1:
        for index, source in enumerate(files):
            run(index, source)
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(files))) as pool:
            futures = {
                pool.submit(run, index, source): (index, source)
                for index, source in enumerate(files)
            }
            for future in as_completed(futures):
                # ``run`` records outcomes; re-raising here would only surface
                # a callback bug, which should indeed propagate.
                future.result()

    outcomes.sort(key=lambda item: item[0])
    results = tuple(result for _, result, _ in outcomes if result is not None)
    failures = tuple(
        BatchFailure(
            source=files[index],
            error_type=type(error).__name__,
            message=str(error),
        )
        for index, _, error in outcomes
        if error is not None
    )
    return BatchReport(
        results=results,
        failures=failures,
        elapsed_s=time.perf_counter() - started,
        scanned=len(files),
    )


def compress_directory(
    directory: PathLike,
    output: PathLike | None = None,
    *,
    recursive: bool = False,
    options: OptionsLike = None,
    workers: int = 1,
    on_result: Callable[[CompressionResult], None] | None = None,
    on_error: Callable[[p.Path, Exception], None] | None = None,
    **overrides: t.Any,
) -> BatchReport:
    """Compress every supported image under *directory*."""
    return compress_many(
        [directory],
        output,
        recursive=recursive,
        options=options,
        workers=workers,
        on_result=on_result,
        on_error=on_error,
        **overrides,
    )
