"""Click command line interface for imagepress."""

from __future__ import annotations

import json
import os
import pathlib as p
import typing as t

import click

from . import __version__
from .engines import available_formats
from .errors import ImagePressError
from .formats import FORMATS, output_formats
from .options import Budget, CompressionOptions
from .pipeline import compress_many
from .result import BatchReport, CompressionResult
from .type import Effort, Quality


class QualityParam(click.ParamType):
    name = "quality"

    def convert(
        self,
        value: t.Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> Quality:
        if isinstance(value, int) and not isinstance(value, bool):
            number = value
        else:
            lowered = str(value).strip().lower()
            if lowered == "auto":
                return "auto"
            if lowered == "lossless":
                return "lossless"
            try:
                number = int(lowered)
            except ValueError:
                self.fail(
                    "quality must be auto, lossless or an integer 0..100",
                    param,
                    ctx,
                )
        if not 0 <= number <= 100:
            self.fail("quality must be between 0 and 100", param, ctx)
        return number


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} GiB"


def _print_formats() -> None:
    status = available_formats()
    click.echo(
        f"{'format':<6} {'encode':<7} {'ready':<6} {'alpha':<6} {'lossless':<9} suffix"
    )
    click.echo("-" * 58)
    for name, spec in FORMATS.items():
        can_encode = "yes" if spec.can_encode else "no"
        ready = "-" if not spec.can_encode else ("yes" if status.get(name) else "no")
        click.echo(
            f"{name:<6} {can_encode:<7} {ready:<6} "
            f"{'yes' if spec.supports_alpha else 'no':<6} "
            f"{'yes' if spec.supports_lossless else 'no':<9} {spec.suffix}"
        )


def _quality_label(result: CompressionResult) -> str:
    if result.quality == "original":
        return "original"
    if result.output_format == "PNG" and result.palette_colors is not None:
        return f"PNG {result.palette_colors}c"
    if result.quality == "lossless":
        return f"{result.output_format} lossless"
    if isinstance(result.quality, int):
        return f"{result.output_format} q{result.quality}"
    return result.output_format


def _print_report(report: BatchReport) -> None:
    if not report.results and not report.failures:
        click.echo("no supported images found")
        return

    if report.results:
        header = (
            f"{'source':<28} {'format':<6} {'before':>10} {'after':>10} "
            f"{'saved':>7} {'SSIM':>7} {'dE00 p95':>8} {'time':>7}  output"
        )
        click.echo(header)
        click.echo("-" * len(header))
        for result in report.results:
            metrics = result.metrics
            ssim = f"{metrics.ssim:.4f}" if metrics else "-"
            delta = f"{metrics.delta_e_p95:.2f}" if metrics else "-"
            flag = "" if result.target_met in {True, None} else " !"
            click.echo(
                f"{result.source.name:<28} {result.output_format:<6} "
                f"{_human_bytes(result.source_bytes):>10} "
                f"{_human_bytes(result.output_bytes):>10} "
                f"{result.savings * 100:>6.1f}% {ssim:>7} {delta:>8} "
                f"{result.elapsed_s:>6.2f}s  {result.output} "
                f"[{_quality_label(result)}]{flag}"
            )

    if report.failures:
        click.echo("\nfailures:")
        for failure in report.failures:
            click.echo(f"  {failure.source}: {failure.error_type}: {failure.message}")

    click.echo(
        f"\n{report.succeeded} compressed, {report.failed} failed, "
        f"{report.scanned} scanned in {report.elapsed_s:.2f}s"
    )
    if report.results:
        click.echo(
            f"{_human_bytes(report.total_source_bytes)} -> "
            f"{_human_bytes(report.total_output_bytes)} "
            f"({report.savings * 100:.1f}% smaller)"
        )


@click.command(
    context_settings={
        "help_option_names": ["-h", "--help"],
        "show_default": True,
    }
)
@click.version_option(__version__, prog_name="imagepress")
@click.argument(
    "inputs",
    nargs=-1,
    type=click.Path(exists=True, path_type=p.Path),
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=p.Path),
    help="Output file or directory (default: <name>.min.<ext>).",
)
@click.option(
    "-f",
    "--format",
    "format_",
    type=click.Choice([*output_formats(), "JPG"], case_sensitive=False),
    help="Force output format.",
)
@click.option(
    "-q",
    "--quality",
    type=QualityParam(),
    default="auto",
    help="auto, lossless, or an integer 0..100.",
)
@click.option(
    "--max-colors",
    type=click.IntRange(2, 256),
    default=256,
    help="PNG palette upper bound.",
)
@click.option(
    "--dither",
    type=click.FloatRange(0.0, 1.0),
    default=1.0,
    help="PNG dithering level.",
)
@click.option(
    "--effort",
    type=click.Choice(("fast", "balanced", "max"), case_sensitive=False),
    default="balanced",
    help="Encoder effort.",
)
@click.option(
    "--keep-metadata",
    is_flag=True,
    help="Keep EXIF metadata (ICC is always preserved when valid).",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Stricter guard: SSIM >= 0.99 and Delta E00 p95 <= 2.",
)
@click.option(
    "--no-verify",
    is_flag=True,
    help="Skip metric computation and use conservative fixed qualities.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Replace existing output files.",
)
@click.option(
    "--recursive",
    is_flag=True,
    help="Recurse into directories.",
)
@click.option(
    "--workers",
    type=click.IntRange(min=1),
    default=min(8, os.cpu_count() or 1),
    help="Parallel workers for batches.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Print machine-readable results.",
)
@click.option(
    "--list-formats",
    "list_formats",
    is_flag=True,
    help="List formats, encoder availability and capabilities.",
)
def main(
    inputs: tuple[p.Path, ...],
    output: p.Path | None,
    format_: str | None,
    quality: Quality,
    max_colors: int,
    dither: float,
    effort: str,
    keep_metadata: bool,
    strict: bool,
    no_verify: bool,
    overwrite: bool,
    recursive: bool,
    workers: int,
    json_output: bool,
    list_formats: bool,
) -> None:
    """Compress PNG/JPEG/WebP/AVIF/GIF/BMP/TIFF images."""
    if list_formats:
        _print_formats()
        return
    if not inputs:
        raise click.UsageError("at least one input is required")

    budget = (
        Budget(
            ssim=0.99,
            ssim_lowfreq=0.997,
            delta_e_mean=1.0,
            delta_e_p95=2.0,
            alpha_psnr=45.0,
        )
        if strict
        else Budget()
    )
    try:
        options = CompressionOptions(
            format=format_,
            quality=quality,
            max_colors=max_colors,
            dither=dither,
            effort=t.cast(Effort, effort.lower()),
            keep_metadata=keep_metadata,
            budget=budget,
            verify=not no_verify,
            overwrite=overwrite,
        )
        report = compress_many(
            inputs,
            output,
            options=options,
            recursive=recursive,
            workers=workers,
        )
    except (ImagePressError, OSError) as exc:
        click.echo(f"imagepress: {exc}", err=True)
        raise click.exceptions.Exit(2) from exc

    if json_output:
        click.echo(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        _print_report(report)

    if report.failures:
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    main()
