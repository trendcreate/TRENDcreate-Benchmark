# -*- coding: utf-8 -*-
"""TC Bench 追加プラグイン: 画像生成(Diffusion)ベンチ [スタブ]

このファイルは「後から plugin install で落としてくる拡張ベンチ」の雛形です。
コア(Tc_bench.py)は依存ゼロのまま、このプラグインだけが重いAI依存(onnxruntime /
torch+diffusers)を必要とします。依存が無ければベンチ実行時に自動でスキップされます。

インターフェース:
  NAME, DESCRIPTION
  available() -> (bool, message)   … 依存が揃っているか
  should_run(info) -> bool         … 実行条件(VRAM総量/空き)ゲート
  run(info) -> dict                … {"gpu_diffusion": スコア} を返す

※ 現状は「スタブ」です。バックエンド(ONNX Runtime か PyTorch)確定後に run() の
   実測ロジックを実装します。それまでは available() が False を返し安全にスキップします。
"""

MIN_VRAM_MB = 4096   # VRAM総量 4GB 以上
MIN_FREE_MB = 2048   # 空き 2GB 以上

NAME = "diffusion"
DESCRIPTION = "画像生成(Stable Diffusion)推論ベンチ"


def _detect_backend():
    """利用可能な推論バックエンドを返す。無ければ None。"""
    try:
        import onnxruntime  # noqa: F401
        return "onnxruntime"
    except Exception:
        pass
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
        return "torch"
    except Exception:
        pass
    return None


def available():
    backend = _detect_backend()
    if backend is None:
        return False, "画像生成バックエンド未導入 (onnxruntime または torch+diffusers)"
    # バックエンドはあるが、実測ロジックは未実装(スタブ)。
    return False, "実測ロジックは準備中 (バックエンド={} 検出済み)".format(backend)


def should_run(info):
    total = info.get("gpu_vram_mb") or 0
    free = info.get("gpu_vram_free_mb")
    if total < MIN_VRAM_MB:
        return False
    if free is None:
        return False
    return free >= MIN_FREE_MB


def run(info):
    """本実装では固定プロンプト/解像度/ステップ数で推論し、it/s 等からスコア化する。

    現状はスタブのため空を返す(available() が False なので通常ここには到達しない)。
    """
    return {}
