from __future__ import annotations

import pytest

from tinyimg import Budget, CompressionOptions, OptionError
from tinyimg.metrics import Metrics
from tinyimg.options import resolve_options


def _metrics(**overrides: float) -> Metrics:
    values = {
        "ssim": 0.98,
        "ssim_lowfreq": 0.995,
        "psnr_db": 40.0,
        "delta_e_mean": 1.0,
        "delta_e_p95": 3.0,
        "delta_e_max": 5.0,
        "alpha_psnr_db": 45.0,
    }
    values.update(overrides)
    return Metrics(**values)


def test_defaults_and_modes() -> None:
    options = CompressionOptions()
    assert options.quality_mode == "auto"
    assert options.quality_value is None
    assert options.budget.ssim == 0.97
    assert options.overwrite is False

    assert CompressionOptions(quality=82).quality_mode == "manual"
    assert CompressionOptions(quality=82).quality_value == 82
    assert CompressionOptions(quality="lossless").quality_mode == "lossless"
    assert CompressionOptions(format=".jpg").format == "JPEG"


def test_quality_validation() -> None:
    with pytest.raises(OptionError):
        CompressionOptions(quality=101)
    with pytest.raises(OptionError):
        CompressionOptions(quality=-1)
    with pytest.raises(OptionError):
        CompressionOptions(quality=True)
    with pytest.raises(OptionError):
        CompressionOptions(quality="best")  # type: ignore[arg-type]
    with pytest.raises(OptionError):
        CompressionOptions(max_colors=1)
    with pytest.raises(OptionError):
        CompressionOptions(dither=1.5)
    with pytest.raises(OptionError):
        CompressionOptions(background=(0, 0, 300))
    with pytest.raises(OptionError):
        CompressionOptions(format="BMP")


def test_budget_mapping_and_thresholds() -> None:
    options = CompressionOptions(
        budget={
            "ssim": 0.99,
            "delta_e_mean": 1.0,
            "delta_e_p95": 2.0,
        }  # type: ignore[arg-type]
    )
    assert isinstance(options.budget, Budget)
    assert options.budget.ssim == 0.99
    assert options.budget.delta_e_p95 == 2.0

    with pytest.raises(OptionError):
        Budget(delta_e_mean=4.0, delta_e_p95=2.0)
    with pytest.raises(OptionError):
        Budget(ssim=1.5)


def test_budget_accepts_palette_and_alpha() -> None:
    budget = Budget()
    assert budget.accepts(_metrics(), palette=False)
    assert budget.accepts(_metrics(), palette=True)
    assert not budget.accepts(_metrics(ssim=0.95), palette=False)
    # Palette mode uses the low-frequency SSIM instead of the full one.
    assert budget.accepts(_metrics(ssim=0.95, ssim_lowfreq=0.995), palette=True)
    assert not budget.accepts(_metrics(alpha_psnr_db=30.0))
    assert budget.accepts(_metrics(alpha_psnr_db=None))  # type: ignore[arg-type]


def test_options_mapping_round_trip() -> None:
    original = CompressionOptions(
        format="webp",
        quality=80,
        max_colors=128,
        dither=0.5,
        effort="fast",
        keep_metadata=True,
        background=(1, 2, 3),
        budget=Budget(ssim=0.99),
        verify=False,
        overwrite=True,
    )
    restored = CompressionOptions.fromMapping(original.as_dict())
    assert restored == original
    assert restored.model_dump(mode="json") == original.as_dict()


def test_resolve_options_rejects_ambiguous_input() -> None:
    with pytest.raises(TypeError):
        resolve_options(CompressionOptions(), {"quality": 80})
    assert resolve_options({"quality": 80}).quality == 80
    assert resolve_options(CompressionOptions(quality=70)).quality == 70


def test_with_budget_revalidates() -> None:
    options = CompressionOptions(quality=80)
    changed = options.with_budget(Budget(ssim=0.99))
    assert changed.quality == 80
    assert changed.budget.ssim == 0.99
    assert options.budget.ssim == 0.97
