#!/usr/bin/env python3
"""Generate the benchmark image set.

The real photograph (samples/photo.jpg) is downloaded once from Lorem Picsum
(Unsplash). Everything else is rendered locally so the repository stays
self-contained and the benchmark is reproducible.

Run: uv run python scripts/make_samples.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import pillow_avif  # noqa: F401  (registers AVIF support)
except ImportError:  # pragma: no cover - optional extra
    pillow_avif = None

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
PHOTO = SAMPLES / "photo.jpg"


def run_chrome(url: str, out: Path, width: int, height: int, transparent: bool) -> None:
    cmd = [
        "google-chrome",
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        f"--window-size={width},{height}",
        "--virtual-time-budget=2500",
        f"--screenshot={out}",
        url,
    ]
    if transparent:
        cmd.insert(-1, "--default-background-color=00000000")
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def make_screenshot() -> None:
    html = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 1440px; height: 900px; overflow: hidden; }
  body {
    font-family: "DejaVu Sans", sans-serif;
    background: radial-gradient(1200px 700px at 80% -10%, #26346b 0%, #0d1226 55%, #080b17 100%);
    color: #e8ecff; display: flex;
  }
  .sidebar {
    width: 232px; padding: 28px 20px; border-right: 1px solid rgba(255,255,255,.07);
    background: rgba(7,10,23,.55); display: flex; flex-direction: column; gap: 26px;
  }
  .brand { display: flex; align-items: center; gap: 11px; padding: 0 8px; }
  .mark {
    width: 34px; height: 34px; border-radius: 10px;
    background: linear-gradient(135deg, #62f0c5, #4f8dff 55%, #a06bff);
    box-shadow: 0 0 22px rgba(79,141,255,.45);
  }
  .brand b { font-size: 17px; letter-spacing: .2px; }
  .brand span { display: block; font-size: 10px; color: #8e97b8; letter-spacing: 1.6px; }
  nav { display: flex; flex-direction: column; gap: 6px; }
  .item {
    padding: 11px 12px; border-radius: 9px; font-size: 13px; color: #9aa4c5;
    display: flex; align-items: center; gap: 10px;
  }
  .item.active { background: rgba(79,141,255,.16); color: #e9efff; border: 1px solid rgba(79,141,255,.28); }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: #56618a; }
  .item.active .dot { background: #62f0c5; box-shadow: 0 0 8px #62f0c5; }
  .upgrade {
    margin-top: auto; padding: 15px; border-radius: 12px; font-size: 12px; line-height: 1.55;
    background: linear-gradient(145deg, rgba(98,240,197,.13), rgba(160,107,255,.16));
    border: 1px solid rgba(160,107,255,.25); color: #c9d1ee;
  }
  .upgrade b { display: block; color: #fff; margin-bottom: 4px; }
  main { flex: 1; padding: 30px 38px; display: flex; flex-direction: column; gap: 22px; }
  header { display: flex; align-items: center; justify-content: space-between; }
  h1 { font-size: 26px; font-weight: 700; letter-spacing: -.4px; }
  h1 small { display: block; font-size: 12px; font-weight: 400; color: #8e97b8; margin-top: 5px; }
  .search {
    width: 300px; padding: 11px 14px; border-radius: 10px; font-size: 12px; color: #7f89aa;
    background: rgba(255,255,255,.045); border: 1px solid rgba(255,255,255,.09);
  }
  .avatar {
    width: 38px; height: 38px; border-radius: 50%;
    background: linear-gradient(135deg, #ffb86c, #ff6b9d 60%, #a06bff);
    border: 2px solid rgba(255,255,255,.18);
  }
  .header-right { display: flex; align-items: center; gap: 16px; }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
  .card {
    background: linear-gradient(160deg, rgba(255,255,255,.065), rgba(255,255,255,.022));
    border: 1px solid rgba(255,255,255,.085); border-radius: 15px; padding: 18px 19px;
    box-shadow: 0 18px 50px rgba(0,0,0,.18);
  }
  .label { font-size: 11px; color: #8e97b8; letter-spacing: .4px; text-transform: uppercase; }
  .value { font-size: 27px; font-weight: 700; margin-top: 9px; letter-spacing: -.6px; }
  .delta { font-size: 11px; margin-top: 7px; color: #62f0c5; }
  .delta.red { color: #ff8a9b; }
  .grid { display: grid; grid-template-columns: 1.65fr 1fr; gap: 16px; flex: 1; min-height: 0; }
  .chart-card { display: flex; flex-direction: column; }
  .chart-head { display: flex; justify-content: space-between; align-items: baseline; }
  .chart-head h3 { font-size: 14px; font-weight: 600; }
  .chart-head span { font-size: 11px; color: #8e97b8; }
  .legend { display: flex; gap: 16px; font-size: 11px; color: #8e97b8; margin-top: 8px; }
  .legend i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 5px; }
  svg { width: 100%; height: 100%; margin-top: 6px; }
  .right { display: flex; flex-direction: column; gap: 16px; }
  .donut-wrap { display: flex; align-items: center; gap: 18px; }
  .donut { width: 132px; height: 132px; border-radius: 50%; position: relative;
    background: conic-gradient(#62f0c5 0 42%, #4f8dff 42% 72%, #a06bff 72% 88%, #ff8a9b 88% 100%); }
  .donut::after { content: ""; position: absolute; inset: 22px; border-radius: 50%; background: #131a31; }
  .donut-label { position: absolute; inset: 0; display: grid; place-items: center; z-index: 2; }
  .donut-label b { font-size: 24px; }
  .donut-label small { display: block; font-size: 9px; color: #8e97b8; text-align: center; letter-spacing: .8px; }
  .rows { display: flex; flex-direction: column; gap: 12px; flex: 1; }
  .row { display: flex; align-items: center; gap: 10px; font-size: 11px; color: #9aa4c5; }
  .row b { color: #e8ecff; font-weight: 500; }
  .bar { flex: 1; height: 6px; border-radius: 3px; background: rgba(255,255,255,.07); overflow: hidden; }
  .bar i { display: block; height: 100%; border-radius: 3px; }
  .table { display: grid; grid-template-columns: 1.5fr 1fr 1fr .8fr; gap: 0; font-size: 11px; }
  .table div { padding: 9px 4px; border-bottom: 1px solid rgba(255,255,255,.055); color: #a7b0cf; }
  .table .head { display: contents; }
  .table .head div { color: #707a9c; font-size: 10px; text-transform: uppercase; letter-spacing: .7px; }
  .pill { display: inline-block; padding: 3px 8px; border-radius: 20px; font-size: 9px;
    color: #62f0c5; background: rgba(98,240,197,.11); border: 1px solid rgba(98,240,197,.22); }
  .pill.blue { color: #8fb3ff; background: rgba(79,141,255,.12); border-color: rgba(79,141,255,.25); }
</style>
</head>
<body>
  <aside class="sidebar">
    <div class="brand">
      <div class="mark"></div>
      <div><b>Aurora</b><span>ANALYTICS</span></div>
    </div>
    <nav>
      <div class="item active"><span class="dot"></span> Overview</div>
      <div class="item"><span class="dot"></span> Audience</div>
      <div class="item"><span class="dot"></span> Revenue</div>
      <div class="item"><span class="dot"></span> Campaigns</div>
      <div class="item"><span class="dot"></span> Reports</div>
      <div class="item"><span class="dot"></span> Settings</div>
    </nav>
    <div class="upgrade"><b>Pro insights</b>Unlock cohort analysis and unlimited exports with Aurora Pro.</div>
  </aside>
  <main>
    <header>
      <h1>Overview<small>Tuesday, 18 October · Last 30 days</small></h1>
      <div class="header-right">
        <div class="search">Search metrics, segments, reports…</div>
        <div class="avatar"></div>
      </div>
    </header>
    <section class="kpis">
      <div class="card"><div class="label">Sessions</div><div class="value">184,392</div><div class="delta">↑ 12.8% vs last period</div></div>
      <div class="card"><div class="label">Conversion</div><div class="value">4.62%</div><div class="delta">↑ 0.41 pp vs last period</div></div>
      <div class="card"><div class="label">Revenue</div><div class="value">$92.4k</div><div class="delta">↑ 8.3% vs last period</div></div>
      <div class="card"><div class="label">Bounce rate</div><div class="value">31.7%</div><div class="delta red">↓ 2.1% vs last period</div></div>
    </section>
    <section class="grid">
      <div class="card chart-card">
        <div class="chart-head"><h3>Sessions over time</h3><span>Oct 1 – Oct 18</span></div>
        <div class="legend"><span><i style="background:#4f8dff"></i>This period</span><span><i style="background:#62f0c5"></i>Previous</span></div>
        <svg viewBox="0 0 760 330" preserveAspectRatio="none">
          <defs>
            <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#4f8dff" stop-opacity=".36"/>
              <stop offset="1" stop-color="#4f8dff" stop-opacity="0"/>
            </linearGradient>
            <linearGradient id="line" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stop-color="#4f8dff"/><stop offset="1" stop-color="#62f0c5"/>
            </linearGradient>
          </defs>
          <g stroke="rgba(255,255,255,.07)" stroke-width="1">
            <line x1="0" y1="60" x2="760" y2="60"/><line x1="0" y1="130" x2="760" y2="130"/>
            <line x1="0" y1="200" x2="760" y2="200"/><line x1="0" y1="270" x2="760" y2="270"/>
          </g>
          <path d="M0 260 C40 250 55 210 95 220 S150 190 190 200 S245 150 290 165 S340 135 385 150 S440 95 485 120 S535 80 585 95 S635 60 680 75 S730 42 760 55 L760 330 L0 330 Z" fill="url(#fill)"/>
          <path d="M0 260 C40 250 55 210 95 220 S150 190 190 200 S245 150 290 165 S340 135 385 150 S440 95 485 120 S535 80 585 95 S635 60 680 75 S730 42 760 55" fill="none" stroke="url(#line)" stroke-width="3" stroke-linecap="round"/>
          <path d="M0 285 C50 280 70 250 110 255 S170 235 210 245 S265 215 310 225 S365 195 410 205 S465 175 510 185 S560 160 610 170 S670 145 720 155 S745 150 760 150" fill="none" stroke="#62f0c5" stroke-opacity=".65" stroke-width="2" stroke-dasharray="5 6"/>
          <circle cx="680" cy="75" r="5" fill="#62f0c5"/><circle cx="680" cy="75" r="10" fill="#62f0c5" fill-opacity=".18"/>
        </svg>
      </div>
      <div class="right">
        <div class="card">
          <div class="chart-head"><h3>Traffic sources</h3><span>Share</span></div>
          <div class="donut-wrap" style="margin-top:14px">
            <div class="donut"><div class="donut-label"><div><b>72%</b><small>ORGANIC</small></div></div></div>
            <div class="rows">
              <div class="row"><span class="dot" style="background:#62f0c5"></span><b>Organic</b><span class="bar"><i style="width:74%;background:#62f0c5"></i></span><span>42%</span></div>
              <div class="row"><span class="dot" style="background:#4f8dff"></span><b>Direct</b><span class="bar"><i style="width:54%;background:#4f8dff"></i></span><span>30%</span></div>
              <div class="row"><span class="dot" style="background:#a06bff"></span><b>Social</b><span class="bar"><i style="width:29%;background:#a06bff"></i></span><span>16%</span></div>
              <div class="row"><span class="dot" style="background:#ff8a9b"></span><b>Referral</b><span class="bar"><i style="width:18%;background:#ff8a9b"></i></span><span>12%</span></div>
            </div>
          </div>
        </div>
        <div class="card" style="flex:1">
          <div class="chart-head"><h3>Top pages</h3><span>Views</span></div>
          <div class="table" style="margin-top:10px">
            <div class="head"><div>Page</div><div>Views</div><div>Conv.</div><div>Trend</div></div>
            <div><b style="color:#e8ecff">/pricing</b></div><div>24,891</div><div>6.8%</div><div><span class="pill">↑ 18%</span></div>
            <div><b style="color:#e8ecff">/product</b></div><div>19,402</div><div>5.1%</div><div><span class="pill blue">↑ 9%</span></div>
            <div><b style="color:#e8ecff">/blog/ai</b></div><div>16,277</div><div>3.7%</div><div><span class="pill">↑ 21%</span></div>
            <div><b style="color:#e8ecff">/docs</b></div><div>12,055</div><div>2.9%</div><div><span class="pill blue">↑ 4%</span></div>
          </div>
        </div>
      </div>
    </section>
  </main>
</body>
</html>"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dashboard.html"
        path.write_text(html, encoding="utf-8")
        run_chrome(
            path.as_uri(), SAMPLES / "screenshot.png", 1440, 900, transparent=False
        )


def make_logo() -> None:
    svg = r"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="300" viewBox="0 0 900 300">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#62f0c5"/><stop offset=".55" stop-color="#4f8dff"/><stop offset="1" stop-color="#a06bff"/>
    </linearGradient>
    <linearGradient id="shine" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity=".34"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x="30" y="60" width="180" height="180" rx="48" fill="url(#g)"/>
  <rect x="42" y="72" width="156" height="76" rx="34" fill="url(#shine)"/>
  <path d="M82 205 L120 95 L158 205 M101 168 L143 168" fill="none" stroke="#ffffff" stroke-width="17" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="191" cy="91" r="11" fill="#ffffff" fill-opacity=".9"/>
  <text x="250" y="158" font-family="DejaVu Sans" font-size="82" font-weight="700" fill="#0f172a" letter-spacing="-3">Aurora</text>
  <text x="254" y="202" font-family="DejaVu Sans" font-size="23" font-weight="400" fill="#475569" letter-spacing="8">IMAGE LAB</text>
</svg>"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "logo.svg"
        path.write_text(svg, encoding="utf-8")
        run_chrome(path.as_uri(), SAMPLES / "logo.png", 900, 300, transparent=True)


def make_gradient() -> None:
    w, h = 1280, 800
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    top = np.array([8, 15, 42], dtype=np.float32)
    mid = np.array([38, 62, 120], dtype=np.float32)
    low = np.array([244, 146, 92], dtype=np.float32)
    t = y**0.72
    img = np.where(
        t < 0.58,
        top + (mid - top) * (t / 0.58),
        mid + (low - mid) * ((t - 0.58) / 0.42),
    )
    img = np.broadcast_to(img[:, None, :], (h, w, 3)).copy()
    # Sun glow.
    sx, sy, sr = 0.73 * w, 0.62 * h, 150.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2)
    glow = np.exp(-((d / sr) ** 2))[..., None]
    img = (
        img * (1 - 0.75 * glow)
        + np.array([255, 224, 160], dtype=np.float32) * 0.75 * glow
    )
    # Soft cloud bands.
    rng = np.random.default_rng(7)
    cloud = np.zeros((h, w), dtype=np.float32)
    for _ in range(18):
        cx, cy = rng.uniform(0, w), rng.uniform(0.18 * h, 0.55 * h)
        rx, ry = rng.uniform(80, 260), rng.uniform(10, 34)
        cloud += np.exp(-(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)) * rng.uniform(
            0.04, 0.11
        )
    img = img + cloud[..., None] * np.array([70, 85, 110], dtype=np.float32)
    # Fine film grain keeps the gradient from looking synthetic and stresses dithering.
    img += rng.normal(0, 1.7, (h, w, 1)).astype(np.float32)
    rgb = np.clip(img, 0, 255).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(SAMPLES / "gradient.png", optimize=True)


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    if not PHOTO.exists():
        raise SystemExit(
            f"{PHOTO} is missing. Download it once with:\n"
            "  curl -L 'https://picsum.photos/id/1025/1280/853' -o samples/photo.jpg"
        )
    photo = Image.open(PHOTO).convert("RGB")
    if photo.width > 1280:
        photo = photo.resize(
            (1280, round(photo.height * 1280 / photo.width)), Image.Resampling.LANCZOS
        )
    photo.save(PHOTO, quality=92, optimize=True)
    photo.save(SAMPLES / "photo.png", optimize=True)
    photo.save(SAMPLES / "photo.webp", quality=90, method=6)
    if pillow_avif is not None:
        photo.save(SAMPLES / "photo.avif", quality=90, speed=6)
    else:
        print("pillow-avif-plugin not installed; skipping photo.avif")
    make_screenshot()
    make_logo()
    make_gradient()
    for p in sorted(SAMPLES.iterdir()):
        print(f"{p.name:18} {p.stat().st_size / 1024:9.1f} KiB")


if __name__ == "__main__":
    main()
