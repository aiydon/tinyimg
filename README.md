# tinyimg

tinyimg 是一个本地图片压缩工具，参考 TinyPNG 的思路，为每张图选择编码参数，再用感知指标复核结果。输入支持 PNG, JPEG, WebP, AVIF, GIF, BMP, TIFF。默认保持原格式。依赖由 uv 管理，运行时不访问网络。

7 个基准样本从 3.70 MiB 压到 1.39 MiB，节省 62.5%。全部样本通过默认预算。

```bash
uv sync
uv run tinyimg samples/photo.jpg
uv run tinyimg samples/*.png -o out/ --overwrite
uv run tinyimg samples/photo.png -f webp
```

## TinyPNG 调研

### 官方公开信息

TinyPNG 官方页面说明，PNG 压缩会合并相似颜色，把 24 位真彩色图转成 8 位索引色图，删除无用元数据。官方称视觉效果通常难以察觉，常见节省 50% 到 80%，平均约 75%。JPEG, WebP, AVIF 走有损重编码，编码器根据颜色、纹理和图案选择参数。官方没有公开源码、感知模型和具体参数。逐字节复现不可能。

来源：

- <https://tinypng.com/web/compress>
- <https://tinypng.com/>
- <https://tinypng.com/developers/reference>

### 压缩流程

PNG 的收益主要来自颜色量化。真彩色图有上百万种颜色，索引色图最多 256 种。调色板加 DEFLATE 压缩后，文件通常小很多。误差扩散抖动把量化误差分散到邻近像素，渐变看起来更平滑。

JPEG 本身就是有损格式，继续变小只能重新编码。常见做法包括调整量化表、4:2:0 色度下采样、优化 Huffman 表、渐进式编码和删除元数据。TinyJPG 很可能采用类似流程，具体编码器和参数没有公开。

WebP 和 AVIF 都是块级有损编码。编码器通过质量参数和速度参数控制体积，找到体积与画质的平衡点。

所有格式都可以删除 EXIF, GPS, XMP 和注释。ICC 描述颜色空间，删除后可能改变显示颜色，需要谨慎处理。

### 视觉差异为何不明显

自然图像和界面图存在大量接近的颜色。量化到 256 色后，多数差异低于人眼阈值。抖动把误差分散到邻近像素，渐变更平滑。

人眼对亮度细节更敏感，对色度细节不敏感。4:2:0 下采样减少色度信息，在多数照片上不容易察觉。质量搜索会区分平坦区域和纹理区域，比全图固定质量更稳。

这些结论有边界。印刷、医学影像、法证材料、带小字的截图、平滑天空仍需要人工复核，或者使用无损模式。

### 本项目的选择

本项目用 libimagequant 做 PNG 调色板量化，用 Oxipng 做无损重压缩。JPEG, WebP, AVIF 用二分搜索寻找满足预算的最低质量。质量守卫使用 SSIM 和 CIEDE2000，alpha 通道单独计算 PSNR。默认预算为 SSIM 0.97, SSIM 2x 0.99, ΔE00 均值 2.5, p95 6.0, alpha PSNR 40 dB。

TinyPNG 的专有感知模型无法复刻。本项目用开源编码器和可解释指标近似，不声称输出与 TinyPNG 一致。

## 代码结构

| 路径 | 职责 |
|---|---|
| `src/tinyimg/options.py` | 配置与预算，Pydantic 模型 |
| `src/tinyimg/pipeline.py` | 解码、格式路由、写盘、批量调度 |
| `src/tinyimg/result.py` | 结果模型 |
| `src/tinyimg/formats.py` | 格式表、别名、能力 |
| `src/tinyimg/errors.py` | 异常层级 |
| `src/tinyimg/metrics.py` | SSIM, PSNR, CIEDE2000 |
| `src/tinyimg/engines/base.py` | 编码器协议与上下文 |
| `src/tinyimg/engines/registry.py` | 编码器注册表 |
| `src/tinyimg/engines/png.py` | PNG 量化与重压缩 |
| `src/tinyimg/engines/jpeg.py` | JPEG 自适应质量 |
| `src/tinyimg/engines/webp.py` | WebP 有损与无损 |
| `src/tinyimg/engines/avif.py` | AVIF 编码 |
| `src/tinyimg/engines/gif.py` | GIF 无损优化 |
| `src/tinyimg/cli.py` | Click 命令行 |
| `src/tinyimg/type.py` | 类型别名 |
| `tests/` | 选项、指标、引擎、批量、命令行测试 |

pipeline 不依赖具体编码器。engines 只接收图片和上下文，返回 bytes 和指标，不碰文件系统。移植时通常只需要替换解码器、注册编码器，或者修改格式表。

## 压缩策略

| 格式 | 做法 | 参数 | 兜底 |
|---|---|---|---|
| PNG | libimagequant 调色板量化，Oxipng 重压缩 | 自动尝试 256, 128, 64, 32 色，dither 默认 1.0 | 预算不通过时回退无损 |
| JPEG | 自适应质量重编码，渐进式，q 低于 90 用 4:2:0 | auto 在 60 到 95 之间二分 | 重编码不更小就保留原图 |
| WebP | 有损重编码，alpha 无损 | auto 在 50 到 95 之间二分，method 4 | 重编码不更小就保留原图 |
| AVIF | AV1 重编码 | auto 在 40 到 95 之间二分，speed 6 | 未安装 avif 扩展时明确报错 |
| GIF | 保留全部帧，只做无损优化 | optimize=True | 手动 quality 会报错 |
| BMP, TIFF | 转为 PNG | 默认输出 PNG | 可以显式指定输出格式 |
| 16 位 PNG | 不做有损量化 | 无损重压缩 | 保留 16 位 |

同一格式下，候选结果不小于原文件时保留原文件。输出默认不覆盖。输出路径等于源文件时直接拒绝。动画 GIF 只做无损优化，保留帧数、时长和循环。APNG 和动画 WebP 暂不支持。多页 TIFF 只处理第一页。

## 质量守卫

| 指标 | 默认阈值 | 范围 | 说明 |
|---|---:|---|---|
| SSIM | ≥ 0.970 | JPEG, WebP, AVIF, 无损 | 全分辨率，11×11 Gaussian，Rec.709 luma |
| SSIM 2x | ≥ 0.990 | PNG 调色板 | 2x2 盒式下采样 |
| ΔE00 均值 | ≤ 2.5 | 有损路径 | 颜色偏移平均水平 |
| ΔE00 p95 | ≤ 6.0 | 有损路径 | 95% 像素不超过该值 |
| alpha PSNR | ≥ 40 dB | 含 alpha 输出 | 半透明边缘 |

PNG 调色板路径使用 SSIM 2x 验收。误差扩散抖动会制造高频差异，全分辨率 SSIM 容易把这种差异判成结构损失。2x2 盒式下采样能过滤抖动噪声，色带和边缘错误仍会保留。表格仍报告全分辨率 SSIM，方便对照。

`--strict` 会把阈值收紧到 SSIM 0.99, SSIM 2x 0.997, ΔE00 均值 1.0, p95 2.0, alpha PSNR 45 dB。已经压缩过的 JPEG 可能找不到更小的重编码，此时保留原文件。

## 元数据

编码前应用 EXIF 方向，把旋转写进像素。`keep_metadata=True` 时保留其余 EXIF，并把方向设为 1。默认删除 EXIF, GPS, XMP 和注释。ICC 在色彩空间不变时保留。转 JPEG 时默认用白色背景压平 alpha，`background` 可以换成其他颜色。指标在白色背景上合成透明像素，alpha 单独计算 PSNR。宽色域 ICC 没有做完整色彩管理，指标可能偏乐观。

## 安装

```bash
uv sync
uv run tinyimg --version
uv run tinyimg --list-formats
```

开发环境包含 Ruff, pytest 和 AVIF 插件。

作为库安装：

```bash
pip install tinyimg
pip install "tinyimg[avif]"
pip install "tinyimg[full]"
```

核心依赖为 Pillow, NumPy, imagequant, pyoxipng, Pydantic, Click。AVIF 是可选依赖。

质量检查：

```bash
make check
```

这条命令依次执行 uv format, ruff check, ty check 和 pytest。也可以单独运行：

```bash
uv format
uv run ruff check src tests scripts
uv tool run ty check src/tinyimg
uv run pytest -q
```

## Python 接口

```python
from tinyimg import Budget, CompressionOptions, compress_image

options = CompressionOptions(
    quality="auto",
    effort="balanced",
    overwrite=True,
    budget=Budget(ssim=0.97, ssim_lowfreq=0.99, delta_e_p95=6.0),
)
result = compress_image("samples/photo.jpg", "out/photo.jpg", options=options)
print(result.savings)
print(result.metrics.ssim)
print(result.metrics.delta_e_p95)
```

批量接口：

```python
from tinyimg import CompressionOptions, compress_many

report = compress_many(
    ["samples", "assets/logo.png"],
    "out/",
    recursive=True,
    workers=4,
    options=CompressionOptions(overwrite=True),
)
print(report.succeeded, report.failed, report.savings)
for failure in report.failures:
    print(failure.source, failure.error_type, failure.message)
```

失败项会记录到 `report.failures`，整批不会中断。需要让失败直接抛异常时调用 `report.raise_for_failures`。

无损模式：

```python
compress_image("screenshots/ui.png", quality="lossless", overwrite=True)
```

转格式：

```python
compress_image("samples/photo.png", "out/photo.webp", format="WEBP")
compress_image("samples/photo.jpg", "out/photo.avif", format="AVIF")
```

配置可以来自 JSON。Pydantic 会完成校验。

```python
import json

from tinyimg import CompressionOptions, compress_image

config = json.loads(open("tinyimg.json").read())
options = CompressionOptions.model_validate(config)
print(options.model_dump())
result = compress_image("in.png", "out.png", options=options)
```

也可以直接传 mapping：

```python
result = compress_image(
    "in.png",
    "out.png",
    options={"quality": 80, "overwrite": True},
)
```

`verify=False` 时跳过指标计算，使用固定质量。JPEG 82, WebP 80, AVIF 65, PNG 256 色。`metrics` 和 `target_met` 为 `None`。

## 参数

`compress_image` 接收源路径、输出路径、`options` 和关键字覆盖项。`options` 可以是 `CompressionOptions`、mapping 或 `None`。`options` 和关键字覆盖项只能选一种，一起传入会报错。

`CompressionOptions` 是 frozen Pydantic 模型，可以跨线程共享。

| 字段 | 默认 | 作用 |
|---|---|---|
| `format` | `None` | 强制输出 PNG, JPEG, WEBP, GIF, AVIF。默认保持原格式，BMP 和 TIFF 转为 PNG |
| `quality` | `"auto"` | auto 感知搜索，0 到 100 固定质量，lossless 只去冗余 |
| `max_colors` | `256` | PNG 调色板上限，范围 2 到 256 |
| `dither` | `1.0` | PNG 抖动强度，范围 0 到 1 |
| `effort` | `"balanced"` | fast, balanced, max。影响调色板搜索、Oxipng 压缩、WebP 和 AVIF 速度 |
| `keep_metadata` | `False` | 保留 EXIF，ICC 在有效时始终保留 |
| `background` | `(255, 255, 255)` | 转 JPEG 时压平 alpha 的背景色 |
| `budget` | `Budget()` | 感知预算 |
| `verify` | `True` | 计算指标并驱动质量搜索 |
| `overwrite` | `False` | 允许替换已存在输出。输出等于源文件时始终拒绝 |

`Budget` 字段：

| 字段 | 默认 | 作用 |
|---|---:|---|
| `ssim` | `0.97` | 全分辨率 SSIM 预算 |
| `ssim_lowfreq` | `0.99` | PNG 调色板 2x 下采样 SSIM 预算 |
| `delta_e_mean` | `2.5` | CIEDE2000 均值预算 |
| `delta_e_p95` | `6.0` | CIEDE2000 95 分位预算 |
| `alpha_psnr` | `40.0` | alpha 通道 PSNR 预算 |

返回值 `CompressionResult` 包含源路径、输出路径、源格式、输出格式、编码器名称、字节数、节省比例、压缩比、耗时、编码质量、调色板颜色数、`target_met`、备注和 `Metrics`。`Metrics` 包含 `ssim`, `ssim_lowfreq`, `psnr_db`, `delta_e_mean`, `delta_e_p95`, `delta_e_max`, `alpha_psnr_db`。`result.as_dict` 可以直接写入 JSON 日志。

异常层级为 `TinyImgError`, `CompressionError`, `OptionError`, `UnsupportedFormatError`, `DecodeError`, `EncodeError`, `OutputExistsError`。批量接口把单图异常记录为 `BatchFailure`。

## 命令行

```bash
uv run tinyimg samples/photo.jpg
uv run tinyimg samples/ assets/ -o out/ --workers 4
uv run tinyimg assets/ -o out/ --recursive --overwrite
uv run tinyimg samples/photo.jpg -q 85
uv run tinyimg samples/photo.png -f WEBP
uv run tinyimg samples/gradient.png --strict
uv run tinyimg samples/photo.jpg --no-verify
uv run tinyimg --list-formats
uv run tinyimg samples/logo.png --json
```

未指定 `-o` 时写入 `name.min.ext`。默认不覆盖。多输入时 `-o` 必须是目录。`--json` 输出 `scanned`, `elapsed_s`, `totals`, `results`, `failures` 五个字段。退出码 0 表示成功，1 表示有文件失败，2 表示参数或输出配置错误。

## 移植

代码分为 pipeline 和 engines 两层。pipeline 负责解码、命名、写盘和批量调度。engines 只负责把图片编码成 bytes，并返回测量结果。

替换编码器：

```python
from tinyimg import EncodeAttempt, EncodeContext, register_encoder


class MyPngEncoder:
    name = "PNG"
    supports_lossless = True
    install_hint = ""

    def available(self) -> bool:
        return True

    def encode(self, image, ctx: EncodeContext) -> EncodeAttempt:
        data = my_backend.encode(
            image,
            quality=ctx.options.quality,
            icc=ctx.icc,
        )
        return EncodeAttempt(
            data=data,
            metrics=ctx.measure(data),
            quality="custom",
            note="my backend",
        )


register_encoder(MyPngEncoder(), replace=True)
```

内置编码器也使用同一协议。新增格式时，先在 `formats.py` 的 `FORMATS` 登记能力，再注册编码器。pipeline 会自动完成格式路由。

替换解码器时，改 `pipeline._load`。返回值需要包含图片、格式、动画标记、EXIF、ICC 和原始字节。

`CompressionOptions` 和 `CompressionResult` 都是 Pydantic 模型，可以 pickle，也可以跨线程共享。批量 `workers` 大于 1 时，回调在 worker 线程执行，回调需要线程安全。

## 基准结果

样本包括照片、照片转 PNG, WebP, AVIF、网页截图、透明 logo、平滑渐变。`photo.*` 来自 Lorem Picsum 和 Unsplash，其余本地生成。默认使用 `quality="auto"` 和 `effort="balanced"`。

<!-- BENCHMARK:START -->
环境：Python 3.13.5, Pillow 13.0.0, NumPy 2.5.4, imagequant 1.1.5, pyoxipng 9.1.1, AVIF plugin 1.6.0, effort=balanced

| 样本 | 格式 | 原始 | 压缩后 | 节省 | SSIM | SSIM 2x | PSNR | ΔE00 均值 | ΔE00 p95 | 编码 | 耗时 | 目标 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| `gradient.png` | PNG | 964.4 KiB | 238.7 KiB | 75.2% | 0.9710 | 0.9926 | 42.6 dB | 0.75 | 2.14 | PNG 127c | 7.24s | 通过 |
| `logo.png` | PNG | 28.5 KiB | 7.8 KiB | 72.7% | 0.9886 | 0.9987 | 42.6 dB | 0.21 | 1.34 | PNG 32c | 1.89s | 通过 |
| `photo.avif` | AVIF | 252.6 KiB | 114.5 KiB | 54.7% | 0.9700 | 0.9909 | 37.7 dB | 1.59 | 3.84 | AVIF q64 | 9.92s | 通过 |
| `photo.jpg` | JPEG | 296.6 KiB | 183.9 KiB | 38.0% | 0.9703 | 0.9944 | 37.4 dB | 1.52 | 3.77 | JPEG q82 | 5.60s | 通过 |
| `photo.png` | PNG | 1.54 MiB | 625.2 KiB | 60.5% | 0.9738 | 0.9955 | 38.7 dB | 2.29 | 5.49 | PNG 256c | 4.62s | 通过 |
| `photo.webp` | WEBP | 214.2 KiB | 146.2 KiB | 31.7% | 0.9724 | 0.9897 | 38.1 dB | 1.66 | 3.90 | WEBP q81 | 8.25s | 通过 |
| `screenshot.png` | PNG | 456.1 KiB | 105.1 KiB | 77.0% | 0.9948 | 0.9978 | 45.6 dB | 0.59 | 1.36 | PNG 128c | 12.10s | 通过 |
| **合计** |  | **3.70 MiB** | **1.39 MiB** | **62.5%** |  |  |  |  |  |  | **49.62s** |  |

> SSIM 为全分辨率值，包含抖动噪声。SSIM 2x 为 2x2 盒式下采样后的值，PNG 调色板路径使用它验收。ΔE00 为 CIEDE2000，越小越好。p95 ≤ 6，均值 ≤ 2.5，SSIM 2x ≥ 0.99，alpha PSNR ≥ 40 dB 为默认预算。

### 100% 局部对比

**photo.jpg**。左：原图；中：压缩后；右：差异 ×8。

![photo.jpg comparison](benchmark/previews/photo-jpg.png)

**screenshot.png**。左：原图；中：压缩后；右：差异 ×12。

![screenshot.png comparison](benchmark/previews/screenshot-png.png)

**gradient.png**。左：原图；中：压缩后；右：差异 ×12。

![gradient.png comparison](benchmark/previews/gradient-png.png)

> 预览为 1:1 像素裁剪，避免缩放掩盖压缩痕迹。差异图经过放大，黑色表示完全相同；高倍放大后的噪声/dither 并不等于肉眼可见的差异。

> `photo.jpg` 来自 Lorem Picsum / Unsplash；`photo.png`、`photo.webp`、`photo.avif` 由同一张照片派生；`screenshot.png`、`logo.png`、`gradient.png` 为本地生成。
<!-- BENCHMARK:END -->

结果解读：

- 截图、渐变和 logo 的收益在 72% 到 77% 之间。这些图颜色冗余高，128 色或 32 色足以通过预算。
- 照片 PNG 收益 60.5%，ΔE00 p95 为 5.49。视觉接近，但不是数学无损。
- 已压缩的 JPEG 和 WebP 收益分别为 38.0% 和 31.7%。源文件已经过有损编码，二次压缩空间更小。
- AVIF 源再压缩收益 54.7%。源文件质量较高，自适应搜索找到 q64。
- 7 个样本全部通过默认预算，没有文件变大。总耗时见表格。
- TinyPNG 官方平均 75% 来自它自己的数据集和质量策略。本表使用更保守的守卫，也包含已压缩格式，两者不能直接比较。

复现：

```bash
uv run python scripts/benchmark.py
```

脚本会重写 `benchmark/results.json`, `benchmark/results.md`, `benchmark/previews/`，并更新 README 中 `BENCHMARK` 标记之间的内容。

## 局限

- `quality="auto"` 在 PNG, JPEG, WebP, AVIF 上是有损模式。重要原图请保留备份。
- 需要像素级不变时使用 `quality="lossless"`。JPEG 和 AVIF 会拒绝该模式。
- SSIM 和 CIEDE2000 只是代理指标。小字、细线、肤色、医学影像、印刷品仍建议人工复核。
- 宽色域 ICC 会保留，指标按 sRGB 数值计算，没有做完整色彩管理。
- PNG 调色板最多 256 色。平滑渐变和照片可能回退无损。需要更高压缩率可以转 WebP 或 AVIF。
- GIF 只做无损优化，动画会保留。手动 `quality` 会报错。
- APNG 和动画 WebP 不支持。多页 TIFF 只处理第一页。
- 不支持 SVG 和 JPEG XL。BMP 和 TIFF 只作为输入。
- 指标在整张图上计算。超大图会占用较多内存。
- 默认不覆盖输出。输出路径等于源文件时始终拒绝。
- AVIF 的 EXIF 支持取决于插件实现。`keep_metadata=True` 时 EXIF 可能丢失，ICC 会尽量保留。
- 本项目不调用 TinyPNG API，也不声称输出与 TinyPNG 一致。

## 参考

- <https://tinypng.com/web/compress>
- <https://tinypng.com/>
- <https://tinypng.com/developers/reference>
- <https://pngquant.org/lib/>
- <https://github.com/shssoichiro/oxipng>
- <https://github.com/nfrasser/pyoxipng>
- <https://developers.google.com/speed/webp>
- <https://aomediacodec.github.io/av1-avif/>
- <https://github.com/google/zopfli>
- <https://python-pillow.org/>
- <https://github.com/fdintino/pillow-avif-plugin>
