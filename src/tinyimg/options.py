"""Typed configuration objects.

``CompressionOptions`` is the single source of truth for encoder behaviour.
It is a frozen Pydantic model, so it validates JSON/config input, can be shared
by threads, and serializes without a parallel CLI-only layer.
"""

from __future__ import annotations

import typing as t
from collections.abc import Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import OptionError, UnsupportedFormatError
from .formats import FORMATS, normalize_format
from .metrics import Metrics
from .type import Effort, Quality


class _OptionsModel(BaseModel):
    """Pydantic base that maps validation failures onto ``OptionError``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def __init__(self, **data: t.Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise OptionError(str(exc)) from exc

    @classmethod
    def model_validate(cls, obj: t.Any, **kwargs: t.Any) -> t.Self:
        try:
            return super().model_validate(obj, **kwargs)
        except ValidationError as exc:
            raise OptionError(str(exc)) from exc


class Budget(_OptionsModel):
    """Perceptual acceptance thresholds.

    ``ssim`` applies to JPEG/WebP/AVIF and lossless output.  ``ssim_lowfreq``
    applies to dithered PNG palettes and is measured after 2x2 box
    downsampling, so deliberate dither noise is not counted as structural
    loss.  ``delta_e_p95`` is usually the most important number: it bounds the
    worst 5% of colour errors rather than rewarding large flat areas.
    """

    ssim: float = Field(default=0.97, ge=0.0, le=1.0)
    ssim_lowfreq: float = Field(default=0.99, ge=0.0, le=1.0)
    delta_e_mean: float = Field(default=2.5, ge=0.0)
    delta_e_p95: float = Field(default=6.0, ge=0.0)
    alpha_psnr: float = Field(default=40.0, ge=0.0)

    @model_validator(mode="after")
    def _check(self) -> t.Self:
        if self.delta_e_p95 < self.delta_e_mean:
            raise ValueError("delta_e_p95 must be >= delta_e_mean")
        return self

    def accepts(self, metrics: Metrics, *, palette: bool = False) -> bool:
        """Return True when *metrics* fit this budget.

        ``palette=True`` selects the low-frequency SSIM threshold used for
        dithered PNG palettes.
        """
        structural = metrics.ssim_lowfreq if palette else metrics.ssim
        threshold = self.ssim_lowfreq if palette else self.ssim
        if structural < threshold:
            return False
        if metrics.delta_e_p95 > self.delta_e_p95:
            return False
        if metrics.delta_e_mean > self.delta_e_mean:
            return False
        return not (
            metrics.alpha_psnr_db is not None
            and metrics.alpha_psnr_db < self.alpha_psnr
        )

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class CompressionOptions(_OptionsModel):
    """All knobs that affect encoding.

    ``quality``:

    * ``"auto"`` searches for the lowest encoder quality / palette size that
      satisfies ``budget``.  This is the default and the only mode that uses
      the quality guard.
    * ``"lossless"`` removes redundancy without changing decoded pixels.
      JPEG and AVIF reject it; PNG, WebP and GIF support it.
    * an integer ``0..100`` forces that encoder quality.  For PNG it scales
      ``max_colors`` (``100`` means all ``max_colors``).

    ``verify=False`` skips metric computation and uses conservative defaults
    (JPEG 82, WebP 80, AVIF 65, PNG 256 colours).  It is useful for throughput
    pipelines that verify elsewhere, not for unattended "visually lossless"
    work.
    """

    format: str | None = None
    quality: Quality = "auto"
    max_colors: int = Field(default=256, ge=2, le=256)
    dither: float = Field(default=1.0, ge=0.0, le=1.0)
    effort: Effort = "balanced"
    keep_metadata: bool = False
    background: tuple[int, int, int] = (255, 255, 255)
    budget: Budget = Field(default_factory=Budget)
    verify: bool = True
    overwrite: bool = False

    @field_validator("format")
    @classmethod
    def _format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            canonical = normalize_format(value)
        except UnsupportedFormatError as exc:
            raise ValueError(str(exc)) from exc
        if not FORMATS[canonical].can_encode:
            raise ValueError(
                f"{canonical} is an input-only format; choose one of "
                f"{', '.join(name for name, spec in FORMATS.items() if spec.can_encode)}"
            )
        return canonical

    @field_validator("quality", mode="before")
    @classmethod
    def _quality(cls, value: t.Any) -> Quality:
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"auto", "lossless"}:
                return t.cast(Quality, lowered)
            raise ValueError("quality must be 'auto', 'lossless' or 0..100")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("quality must be 'auto', 'lossless' or 0..100")
        if not 0 <= value <= 100:
            raise ValueError("quality must be between 0 and 100")
        return value

    @field_validator("background", mode="before")
    @classmethod
    def _background(cls, value: t.Any) -> tuple[int, int, int]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("background must be an (R, G, B) tuple")
        items = tuple(value)
        if len(items) != 3 or any(
            isinstance(channel, bool)
            or not isinstance(channel, int)
            or not 0 <= channel <= 255
            for channel in items
        ):
            raise ValueError("background must be an (R, G, B) tuple")
        return t.cast(tuple[int, int, int], items)

    @property
    def quality_mode(self) -> str:
        """``"auto"``, ``"lossless"`` or ``"manual"``."""
        return self.quality if isinstance(self.quality, str) else "manual"

    @property
    def quality_value(self) -> int | None:
        """The forced quality for manual mode, else ``None``."""
        return self.quality if isinstance(self.quality, int) else None

    def as_dict(self) -> dict[str, t.Any]:
        """JSON-friendly representation, suitable for config files."""
        return self.model_dump(mode="json")

    @classmethod
    def fromMapping(cls, values: Mapping[str, t.Any]) -> t.Self:
        """Build options from a mapping, e.g. a JSON config file."""
        return cls.model_validate(values)

    def with_budget(self, budget: Budget) -> t.Self:
        """Return a validated copy with a different perceptual budget."""
        return type(self).model_validate({**self.model_dump(), "budget": budget})


type OptionsLike = CompressionOptions | Mapping[str, t.Any] | None


def resolve_options(
    options: OptionsLike,
    overrides: Mapping[str, t.Any] | None = None,
) -> CompressionOptions:
    """Normalize ``options=`` plus keyword overrides into one object.

    Passing both an object and keyword overrides is rejected because it is
    ambiguous which value should win.  Pass either ``options=...`` or keyword
    arguments.
    """
    overrides = dict(overrides or {})
    if options is None:
        return CompressionOptions(**overrides)
    if isinstance(options, CompressionOptions):
        if overrides:
            raise TypeError("pass either options= or keyword options, not both")
        return options
    if isinstance(options, Mapping):
        if overrides:
            raise TypeError("pass either options= or keyword options, not both")
        return CompressionOptions.model_validate(options)
    raise TypeError("options must be CompressionOptions, a mapping or None")
