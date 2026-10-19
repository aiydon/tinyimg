"""Result objects returned by the public API.

The models are frozen Pydantic models and JSON-serializable via ``as_dict()``.
A host service can therefore log or persist results without importing
Pillow-specific types.
"""

from __future__ import annotations

import pathlib as p
import typing as t

from pydantic import BaseModel, ConfigDict

from .errors import CompressionError
from .metrics import Metrics


class EncodeAttempt(BaseModel):
    """One encoder output plus its measured quality.

    Encoders return this instead of writing directly, which keeps the
    encode/search logic independent from path handling and lets callers swap
    or wrap engines.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data: bytes
    metrics: Metrics | None = None
    quality: str | int | None = None
    palette_colors: int | None = None
    note: str = ""


class CompressionResult(BaseModel):
    """Outcome of a single :func:`imagepress.compress_image` call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: p.Path
    output: p.Path
    source_format: str
    output_format: str
    encoder: str
    source_bytes: int
    output_bytes: int
    elapsed_s: float
    metrics: Metrics | None
    target_met: bool | None
    quality: str | int | None = None
    palette_colors: int | None = None
    note: str = ""

    @property
    def savings(self) -> float:
        """Fraction of bytes removed, e.g. ``0.42`` means 42% smaller."""
        return 1.0 - self.output_bytes / self.source_bytes

    @property
    def ratio(self) -> float:
        """Compression ratio (source bytes / output bytes)."""
        return self.source_bytes / self.output_bytes

    def as_dict(self) -> dict[str, t.Any]:
        """JSON-friendly representation with computed fields and metrics."""
        data = self.model_dump(mode="json", exclude={"metrics"})
        data["savings_pct"] = round(self.savings * 100.0, 2)
        data["ratio"] = round(self.ratio, 3)
        data["elapsed_s"] = round(self.elapsed_s, 3)
        data["metrics"] = None if self.metrics is None else self.metrics.as_dict()
        return data


class BatchFailure(BaseModel):
    """One input that could not be processed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: p.Path
    error_type: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return self.model_dump(mode="json")


class BatchReport(BaseModel):
    """Aggregate outcome of :func:`imagepress.compress_many`.

    ``results`` and ``failures`` preserve input order.  ``scanned`` counts
    files discovered after directory expansion and de-duplication.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    results: tuple[CompressionResult, ...]
    failures: tuple[BatchFailure, ...]
    elapsed_s: float
    scanned: int

    @property
    def succeeded(self) -> int:
        return len(self.results)

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def total_source_bytes(self) -> int:
        return sum(result.source_bytes for result in self.results)

    @property
    def total_output_bytes(self) -> int:
        return sum(result.output_bytes for result in self.results)

    @property
    def savings(self) -> float:
        """Aggregate byte savings across successful images (0 if none)."""
        if not self.total_source_bytes:
            return 0.0
        return 1.0 - self.total_output_bytes / self.total_source_bytes

    def as_dict(self) -> dict[str, t.Any]:
        return {
            "scanned": self.scanned,
            "elapsed_s": round(self.elapsed_s, 3),
            "totals": {
                "succeeded": self.succeeded,
                "failed": self.failed,
                "source_bytes": self.total_source_bytes,
                "output_bytes": self.total_output_bytes,
                "savings_pct": round(self.savings * 100.0, 2),
            },
            "results": [result.as_dict() for result in self.results],
            "failures": [failure.as_dict() for failure in self.failures],
        }

    def raise_for_failures(self) -> None:
        """Raise one :class:`CompressionError` if any input failed.

        Useful at a service boundary where partial success must be visible.
        Successful results are still available on the report.
        """
        if not self.failures:
            return
        details = "\n".join(
            f"{failure.source}: {failure.error_type}: {failure.message}"
            for failure in self.failures
        )
        raise CompressionError(f"{len(self.failures)} image(s) failed:\n{details}")
