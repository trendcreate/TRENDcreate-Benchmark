# TC Bench

Lubuntu / antiX などの軽量Linux と Windows の両方で動く、**CPU / GPU ベンチマーク兼システム診断ツール**です。
外部ライブラリ不要（Python3 標準ライブラリのみ）で、結果を JSON に保存して共有・集計できます。

🌐 **ベンチマーク共有ページ:** https://trendcreate.github.io/TRENDcreate-Benchmark/

みんなのスコアをランキング表示し、自分の `score/*.json` を貼り付けてその場で比較できます。
投稿は `score/` にJSONを追加 → `python tools/build_pages.py` で `docs/data.json` 更新 → Pull Request、または Issue にJSONを貼るだけ。

## 構成

| ファイル | OS | 役割 |
|---|---|---|
| `Tc_bench.sh` | Linux / macOS | ベンチマーク本体 |
| `Tc_bench.bat` | Windows | ベンチマーク本体 |
| `Tc_summary.sh` | Linux / macOS | スコア集計・ランキング表示 |
| `Tc_summary.bat` | Windows | スコア集計・ランキング表示 |
| `score/` | 共通 | スコアJSONの保存先（自動生成） |

## 必要環境

- **Python 3.4+**（`multiprocessing`, `math`, `json` など標準ライブラリのみ使用）
- Linux: `lscpu`（システム情報取得）、GPU情報は `nvidia-smi`（NVIDIA）/ `amdgpu` の sysfs・`rocm-smi`・`lspci`（AMD）
- Windows: PowerShell（標準搭載）、GPU情報は `nvidia-smi`（NVIDIA）/ WMI + レジストリ（AMD）

## 使い方

### ベンチマーク実行

**Linux**
```bash
chmod +x Tc_bench.sh    # 初回のみ（スクリプト末尾で自動付与も行います）
./Tc_bench.sh
```

**Windows**
```
Tc_bench.bat をダブルクリック、またはコマンドプロンプトで実行
```

実行すると以下が行われます。

1. **システム情報の表示** — CPUモデル名 / コア数・スレッド数 / L3キャッシュ / GPU名・VRAM
2. **シングルスレッド性能テスト** — 1コアで重い素数＋数学演算
3. **マルチスレッド性能テスト** — 全論理スレッドを100%使用
4. **スコア算出** — 独自スコアをASCIIバーチャートで表示
   - `CPU Single` … シングルコア性能
   - `CPU Multi` … 全スレッド性能
   - `GPU V-Calc` … **NVIDIA / AMD GPU** 検出時。`最大クロック × VRAM(GB)^1.5` ベースの仮想スコア（VRAM容量を重視）。クロックが取得できない場合（AMD等）は公称値で算出（`※クロック公称値` と表示）。どちらも未検出なら安全にスキップ。
5. **スコア保存** — `score/<CPU名>__<GPU名>.json` に保存（過去ベストと自動比較）

### スコア集計・ランキング

`score/` 内の全結果を読み込み、組み合わせごとのベストスコアをランキング表示します。

**Linux**
```bash
./Tc_summary.sh                 # マルチスコア順（既定）
./Tc_summary.sh --sort=single   # シングル順
./Tc_summary.sh --sort=gpu      # GPU V-Calc順
```

**Windows**
```
Tc_summary.bat            （マルチスコア順・既定）
Tc_summary.bat single     （シングル順）
Tc_summary.bat gpu        （GPU V-Calc順）
```

## スコアの共有

`score/` フォルダ内の JSON ファイルをそのまま他の人に渡せば、結果を共有・比較できます。
受け取った JSON を自分の `score/` に置いて集計スクリプトを実行すると、同じランキングに並びます。

### JSON フォーマット（`score/*.json`）

```json
{
  "combo": "AMD_Ryzen_7_4700U__N_A",
  "system": {
    "cpu_model": "AMD Ryzen 7 4700U with Radeon Graphics",
    "architecture": "x86_64",
    "cores_per_socket": "8",
    "logical_processors": 8,
    "l3_cache": "8 MB",
    "gpu_name": null,
    "gpu_vram_mb": null,
    "gpu_sm_clock_mhz": null
  },
  "best":  { "cpu_single": 967.0, "cpu_multi": 4386.0, "gpu_vcalc": null, "multi_ratio": 4.53 },
  "runs":  [ { "timestamp": "...", "scores": { "...": "..." } } ]
}
```

- `best` … 各スコアの過去最高値（集計はこの値を使用）
- `runs` … 実行ごとの履歴（追記されていく）

## 注意・トラブルシューティング

- **`.bat` を編集する場合は改行コードを CRLF にしてください。** LF のままだとコマンドが認識されずエラーになります（VS Code 等で「CRLF」を指定して保存）。
- 文字化けする場合: `.bat` は `chcp 65001`（UTF-8）に切り替えます。コンソールのフォントが日本語対応か確認してください。
- スコアの負荷量は各スクリプト内の `WORK_LIMIT`（既定 `600000`）で調整できます。低速マシンで時間がかかりすぎる場合は小さくしてください。
- 集計時に壊れた / 0バイトの JSON があっても、自動的にスキップして「スキップ: N」と表示します（クラッシュしません）。

## スコアの算出式（参考）

```
CPU Single = 10000 / シングル実行秒数
CPU Multi  = 10000 × 論理スレッド数 / マルチ実行秒数
GPU V-Calc = 最大クロック(MHz) × (VRAM_GB ^ 1.5) / 10   (クロック不明時は公称 1500MHz)
```

スコアは相対比較用の独自指標です。CPU負荷状態（他プロセス・電源/温度による周波数制御）で変動するため、計測はアイドル状態で行うことを推奨します。
