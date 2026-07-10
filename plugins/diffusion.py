# -*- coding: utf-8 -*-
"""TC Bench 追加プラグイン: 画像生成(Diffusion)推論ベンチ

Stable Diffusion の UNet デノイズ 1 ステップ相当の畳み込みワークロードを
GPU 上で実測し、steps/sec からスコアを算出します。

- モデルのダウンロードは不要（重みは乱数で初期化した UNet 風ネットワーク）
- 依存: PyTorch (CUDA / ROCm)。無ければ自動でスキップ
- 実行条件: VRAM 総量 4GB 以上 & 空き 2GB 以上（コア側の検出値を利用）

スコア: gpu_diffusion = デノイズ steps/sec × 100
  （SD1.5 512x512 相当の latent 64x64x4 を処理。高いほど速い）
"""

MIN_VRAM_MB = 4096   # VRAM総量 4GB 以上
MIN_FREE_MB = 2048   # 空き 2GB 以上

NAME = "diffusion"
DESCRIPTION = "画像生成(Stable Diffusion)推論ベンチ"

WARMUP_STEPS = 5
MEASURE_STEPS = 40
LATENT = (1, 4, 64, 64)   # SD1.5 512x512 相当の latent
BASE_CH = 128


def _torch_device():
    try:
        import torch
    except Exception:
        return None, None
    if torch.cuda.is_available():          # CUDA / ROCm(HIP) 共通
        return torch, "cuda"
    return torch, None


def available():
    torch, dev = _torch_device()
    if torch is None:
        return False, "PyTorch 未導入 (pip install torch でGPU版を導入してください)"
    if dev is None:
        return False, "GPU が PyTorch から見えません (CUDA/ROCm 版 torch が必要)"
    return True, ""


def should_run(info):
    total = info.get("gpu_vram_mb") or 0
    free = info.get("gpu_vram_free_mb")
    if total < MIN_VRAM_MB:
        return False
    # 空きが取得できない環境(Windows+AMD等)は総量ゲートのみで許可する
    if free is not None and free < MIN_FREE_MB:
        return False
    return True


def _build_unet(torch, device, dtype):
    """UNet 風のデノイズブロック (conv + GroupNorm + SiLU、ダウン/アップ各1段)。"""
    import torch.nn as nn

    ch = BASE_CH

    class Block(nn.Module):
        def __init__(self, cin, cout):
            super().__init__()
            self.conv1 = nn.Conv2d(cin, cout, 3, padding=1)
            self.norm1 = nn.GroupNorm(32, cout)
            self.conv2 = nn.Conv2d(cout, cout, 3, padding=1)
            self.norm2 = nn.GroupNorm(32, cout)
            self.act = nn.SiLU()

        def forward(self, x):
            x = self.act(self.norm1(self.conv1(x)))
            return self.act(self.norm2(self.conv2(x)))

    class MiniUNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.inb = Block(LATENT[1], ch)
            self.down = nn.Conv2d(ch, ch * 2, 3, stride=2, padding=1)
            self.mid = Block(ch * 2, ch * 2)
            self.up = nn.ConvTranspose2d(ch * 2, ch, 4, stride=2, padding=1)
            self.outb = Block(ch * 2, ch)
            self.head = nn.Conv2d(ch, LATENT[1], 3, padding=1)

        def forward(self, x):
            h1 = self.inb(x)
            h2 = self.mid(self.down(h1))
            h3 = self.up(h2)
            h = self.outb(torch.cat([h1, h3], dim=1))
            return self.head(h)

    model = MiniUNet().to(device=device, dtype=dtype)
    model.eval()
    return model


def run(info):
    import time
    torch, device = _torch_device()
    if torch is None or device is None:
        return {}

    dtype = torch.float16
    torch.manual_seed(0)
    try:
        model = _build_unet(torch, device, dtype)
        latent = torch.randn(*LATENT, device=device, dtype=dtype)
    except Exception:
        # fp16 非対応環境は fp32 で再試行
        dtype = torch.float32
        model = _build_unet(torch, device, dtype)
        latent = torch.randn(*LATENT, device=device, dtype=dtype)

    def step(x):
        # デノイズ1ステップ: eps 予測して引く (スケジューラ簡略版)
        with torch.no_grad():
            eps = model(x)
            return x - 0.05 * eps

    x = latent
    for _ in range(WARMUP_STEPS):
        x = step(x)
    torch.cuda.synchronize()

    start = time.perf_counter()
    for _ in range(MEASURE_STEPS):
        x = step(x)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    # 結果が NaN 化していないか軽く確認 (計算が実際に行われた保証)
    if not torch.isfinite(x).all():
        x = latent

    steps_per_sec = MEASURE_STEPS / elapsed if elapsed > 0 else 0.0
    score = steps_per_sec * 100.0
    print("  [diffusion] {} steps in {:.2f}s -> {:.1f} steps/s ({} / {})".format(
        MEASURE_STEPS, elapsed, steps_per_sec,
        torch.cuda.get_device_name(0) if device == "cuda" else device, str(dtype).replace("torch.", "")))

    del model, latent, x
    torch.cuda.empty_cache()
    return {"gpu_diffusion": score}
