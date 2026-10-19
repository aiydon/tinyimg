from __future__ import annotations

import numpy as np
from PIL import Image

from tinyimg.metrics import _ciede2000, compare


def test_ciede2000_reference_pairs() -> None:
    pairs = [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
        ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
        ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
        ((50.0, -1.1848, -84.8006), (50.0, 0.0, -82.7485), 1.0000),
        ((50.0, -0.9009, -85.5211), (50.0, 0.0, -82.7485), 1.0000),
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
        ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
        ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ]
    for lab_a, lab_b, expected in pairs:
        got = float(
            _ciede2000(
                np.asarray(lab_a, dtype=np.float64),
                np.asarray(lab_b, dtype=np.float64),
            )
        )
        assert abs(got - expected) < 1e-3


def test_identical_images_have_perfect_metrics() -> None:
    rng = np.random.default_rng(4)
    array = rng.integers(0, 256, (48, 64, 4), dtype=np.uint8)
    array[..., 3] = 255
    image = Image.fromarray(array, "RGBA")
    metrics = compare(image, image.copy())
    assert metrics.ssim == 1.0
    assert metrics.ssim_lowfreq == 1.0
    assert metrics.psnr_db == float("inf")
    assert metrics.delta_e_mean == 0.0
    assert metrics.delta_e_p95 == 0.0
    assert metrics.alpha_psnr_db is None
