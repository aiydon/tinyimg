"""tinyimg - adaptive, visually lossless image compression.

Public surface:

* :func:`compress_image` - one file.
* :func:`compress_many` / :func:`compress_directory` - batches with per-item
  failures and optional worker threads.
* :class:`CompressionOptions` / :class:`Budget` - typed configuration.
* :func:`register_encoder` - replace or add a codec backend.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .engines import (
    EncodeContext,
    Encoder,
    available_formats,
    get_encoder,
    register_encoder,
    unregister_encoder,
)
from .errors import (
    CompressionError,
    DecodeError,
    EncodeError,
    OptionError,
    OutputExistsError,
    TinyImgError,
    UnsupportedFormatError,
)
from .formats import (
    FORMATS,
    FormatSpec,
    format_from_suffix,
    normalize_format,
    output_formats,
)
from .metrics import Metrics, compare, delta_e2000, psnr, ssim, ssim_lowfreq
from .options import Budget, CompressionOptions, Effort, OptionsLike, Quality
from .pipeline import compress_directory, compress_image, compress_many
from .result import BatchFailure, BatchReport, CompressionResult, EncodeAttempt

try:
    __version__ = version("tinyimg")
except PackageNotFoundError:  # pragma: no cover - editable/source tree
    __version__ = "0.0.0"

__all__ = [
    "FORMATS",
    "BatchFailure",
    "BatchReport",
    "Budget",
    "CompressionError",
    "CompressionOptions",
    "CompressionResult",
    "DecodeError",
    "Effort",
    "EncodeAttempt",
    "EncodeContext",
    "EncodeError",
    "Encoder",
    "FormatSpec",
    "TinyImgError",
    "Metrics",
    "OptionError",
    "OptionsLike",
    "OutputExistsError",
    "Quality",
    "UnsupportedFormatError",
    "__version__",
    "available_formats",
    "compare",
    "compress_directory",
    "compress_image",
    "compress_many",
    "delta_e2000",
    "format_from_suffix",
    "get_encoder",
    "normalize_format",
    "output_formats",
    "psnr",
    "register_encoder",
    "ssim",
    "ssim_lowfreq",
    "unregister_encoder",
]
