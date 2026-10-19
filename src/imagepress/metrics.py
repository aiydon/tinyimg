"""Pixel-level quality metrics used by the compression guard.

The numbers are deliberately conservative:

* SSIM is computed on gamma-encoded Rec. 709 luma with an 11x11 Gaussian
  window (sigma=1.5), the same convention used by scikit-image.
* CIEDE2000 is computed in CIE Lab (D65) after compositing transparency over
  white, so hidden RGB values under fully transparent pixels do not count.
* Alpha quality is measured separately with PSNR.  A palette quantizer can
  shift semi-transparent edge pixels slightly even when the visible result is
  identical.

SSIM and CIEDE2000 are complementary: SSIM is sensitive to structure/edges,
Delta E is sensitive to colour shifts and banding.
"""

from __future__ import annotations

import math
import typing as t

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, field_serializer

_WHITE = np.array([255.0, 255.0, 255.0], dtype=np.float32)


class Metrics(BaseModel):
    """Difference between a compressed image and its source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ssim: float
    ssim_lowfreq: float
    psnr_db: float
    delta_e_mean: float
    delta_e_p95: float
    delta_e_max: float
    alpha_psnr_db: float | None = None

    @field_serializer("psnr_db", "alpha_psnr_db")
    def _serialize_inf(self, value: float | None) -> float | None:
        if value is None or math.isinf(value):
            return None
        return value

    def as_dict(self) -> dict[str, t.Any]:
        """JSON-friendly metrics with infinities mapped to ``None``."""
        return {
            "ssim": round(self.ssim, 5),
            "ssim_lowfreq": round(self.ssim_lowfreq, 5),
            "psnr_db": (None if math.isinf(self.psnr_db) else round(self.psnr_db, 3)),
            "delta_e_mean": round(self.delta_e_mean, 3),
            "delta_e_p95": round(self.delta_e_p95, 3),
            "delta_e_max": round(self.delta_e_max, 3),
            "alpha_psnr_db": (
                None
                if self.alpha_psnr_db is None or math.isinf(self.alpha_psnr_db)
                else round(self.alpha_psnr_db, 3)
            ),
        }


def _rgba(image: Image.Image) -> np.ndarray:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    return np.asarray(image, dtype=np.uint8)


def _composite_white(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32)
    return rgb * alpha + _WHITE * (1.0 - alpha)


def _gaussian_kernel(size: int, sigma: float) -> np.ndarray:
    coords = np.arange(size, dtype=np.float32) - (size - 1) / 2.0
    kernel = np.exp(-(coords**2) / (2.0 * sigma**2))
    return (kernel / kernel.sum()).astype(np.float32)


def _separable_blur(array: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Gaussian blur via two 1-D convolutions, using symmetric padding."""
    height, width = array.shape
    pad = kernel.shape[0] // 2

    padded = np.pad(array, ((pad, pad), (0, 0)), mode="symmetric")
    rows = np.zeros_like(array, dtype=np.float32)
    for offset, weight in enumerate(kernel):
        rows += weight * padded[offset : offset + height, :]

    padded = np.pad(rows, ((0, 0), (pad, pad)), mode="symmetric")
    result = np.zeros_like(array, dtype=np.float32)
    for offset, weight in enumerate(kernel):
        result += weight * padded[:, offset : offset + width]
    return result


def ssim(a: Image.Image, b: Image.Image) -> float:
    """Mean SSIM of two equally sized images, computed on luma."""
    x = _composite_white(_rgba(a))
    y = _composite_white(_rgba(b))
    if x.shape != y.shape:
        raise ValueError(f"image sizes differ: {x.shape} != {y.shape}")

    luma = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    x = x @ luma
    y = y @ luma

    height, width = x.shape
    size = min(11, height, width)
    if size % 2 == 0:
        size -= 1
    if size < 3:
        return 1.0 if np.array_equal(x, y) else 0.0
    sigma = 1.5 * size / 11.0
    kernel = _gaussian_kernel(size, sigma)

    mu_x = _separable_blur(x, kernel)
    mu_y = _separable_blur(y, kernel)
    mu_x2 = mu_x * mu_x
    mu_y2 = mu_y * mu_y
    mu_xy = mu_x * mu_y

    sigma_x2 = _separable_blur(x * x, kernel) - mu_x2
    sigma_y2 = _separable_blur(y * y, kernel) - mu_y2
    sigma_xy = _separable_blur(x * y, kernel) - mu_xy

    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    numerator = (2.0 * mu_xy + c1) * (2.0 * sigma_xy + c2)
    denominator = (mu_x2 + mu_y2 + c1) * (sigma_x2 + sigma_y2 + c2)
    return float(np.mean(numerator / denominator))


def ssim_lowfreq(a: Image.Image, b: Image.Image, factor: int = 2) -> float:
    """SSIM after box-downsampling, ignoring dither noise.

    Palette quantization with Floyd-Steinberg dithering deliberately adds
    high-frequency pixel noise that a full-resolution SSIM penalises heavily
    even though the perceived gradient is smoother.  Averaging 2x2 blocks
    removes that noise while retaining banding and structural errors.
    """
    x = _composite_white(_rgba(a))
    y = _composite_white(_rgba(b))
    if x.shape != y.shape:
        raise ValueError(f"image sizes differ: {x.shape} != {y.shape}")
    height, width = x.shape[:2]
    size = (max(1, width // factor), max(1, height // factor))
    x_image = Image.fromarray(np.clip(x, 0, 255).astype(np.uint8), "RGB")
    y_image = Image.fromarray(np.clip(y, 0, 255).astype(np.uint8), "RGB")
    x_small = x_image.resize(size, Image.Resampling.BOX)
    y_small = y_image.resize(size, Image.Resampling.BOX)
    return ssim(x_small, y_small)


def psnr(a: Image.Image, b: Image.Image) -> float:
    """PSNR over RGB after compositing over white. ``inf`` for identical input."""
    x = _composite_white(_rgba(a))
    y = _composite_white(_rgba(b))
    mse = float(np.mean((x - y) ** 2))
    if mse == 0.0:
        return float("inf")
    return 10.0 * np.log10(255.0**2 / mse)


def _lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0..255 float) -> CIE Lab (D65)."""
    values = rgb.astype(np.float32) / 255.0
    linear = np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )
    r, g, b = linear[..., 0], linear[..., 1], linear[..., 2]
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b

    xyz = np.stack((x / 0.95047, y / 1.0, z / 1.08883), axis=-1)
    delta = 6.0 / 29.0
    f = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    return np.stack(
        (
            116.0 * f[..., 1] - 16.0,
            500.0 * (f[..., 0] - f[..., 1]),
            200.0 * (f[..., 1] - f[..., 2]),
        ),
        axis=-1,
    )


def _ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """Vectorised CIEDE2000 (Sharma et al. formulation)."""
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    c_bar7 = c_bar**7
    g = 0.5 * (1.0 - np.sqrt(c_bar7 / (c_bar7 + 25.0**7)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    h1p = np.where((a1p == 0.0) & (b1 == 0.0), 0.0, h1p)
    h2p = np.where((a2p == 0.0) & (b2 == 0.0), 0.0, h2p)

    d_lp = l2 - l1
    d_cp = c2p - c1p
    zero_chroma = c1p * c2p == 0.0
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, dh)
    dh = np.where(dh < -180.0, dh + 360.0, dh)
    dh = np.where(zero_chroma, 0.0, dh)
    d_hp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2.0))

    l_bar = (l1 + l2) / 2.0
    c_barp = (c1p + c2p) / 2.0
    h_sum = h1p + h2p
    h_diff = np.abs(h1p - h2p)
    h_bar = np.where(
        zero_chroma,
        h_sum,
        np.where(
            h_diff <= 180.0,
            h_sum / 2.0,
            np.where(h_sum < 360.0, (h_sum + 360.0) / 2.0, (h_sum - 360.0) / 2.0),
        ),
    )

    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_bar))
        + 0.32 * np.cos(np.radians(3.0 * h_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_bar - 63.0))
    )
    d_theta = 30.0 * np.exp(-(((h_bar - 275.0) / 25.0) ** 2))
    c_barp7 = c_barp**7
    r_c = 2.0 * np.sqrt(c_barp7 / (c_barp7 + 25.0**7))
    s_l = 1.0 + (0.015 * (l_bar - 50.0) ** 2) / np.sqrt(20.0 + (l_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_barp
    s_h = 1.0 + 0.015 * c_barp * t
    r_t = -np.sin(np.radians(2.0 * d_theta)) * r_c

    term_l = d_lp / s_l
    term_c = d_cp / s_c
    term_h = d_hp / s_h
    return np.sqrt(term_l**2 + term_c**2 + term_h**2 + r_t * term_c * term_h)


def delta_e2000(a: Image.Image, b: Image.Image) -> np.ndarray:
    """Per-pixel CIEDE2000 differences, flattened."""
    lab_a = _lab(_composite_white(_rgba(a)))
    lab_b = _lab(_composite_white(_rgba(b)))
    return _ciede2000(lab_a, lab_b).reshape(-1)


def alpha_psnr(a: Image.Image, b: Image.Image) -> float | None:
    alpha_a = _rgba(a)[..., 3]
    alpha_b = _rgba(b)[..., 3]
    if alpha_a.min() == 255 and alpha_b.min() == 255:
        return None
    mse = float(np.mean((alpha_a.astype(np.float32) - alpha_b.astype(np.float32)) ** 2))
    if mse == 0.0:
        return float("inf")
    return 10.0 * np.log10(255.0**2 / mse)


def compare(original: Image.Image, compressed: Image.Image) -> Metrics:
    """Compute the full metric bundle for an original/compressed pair."""
    differences = delta_e2000(original, compressed)
    return Metrics(
        ssim=ssim(original, compressed),
        ssim_lowfreq=ssim_lowfreq(original, compressed),
        psnr_db=psnr(original, compressed),
        delta_e_mean=float(differences.mean()),
        delta_e_p95=float(np.percentile(differences, 95)),
        delta_e_max=float(differences.max()),
        alpha_psnr_db=alpha_psnr(original, compressed),
    )


__all__ = [
    "Metrics",
    "compare",
    "delta_e2000",
    "psnr",
    "ssim",
    "ssim_lowfreq",
]
