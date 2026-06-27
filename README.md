# TC Bench

Lubuntu / antiX などの軽量Linux、macOS、Windows で動く、**CPU / GPU ベンチマーク兼システム診断ツール**です。
単一の Python スクリプトで実行・集計でき、外部ライブラリ不要（Python3 標準ライブラリのみ）で結果を JSON に保存して共有できます。

🌐 **ベンチマーク共有ページ:** https://trendcreate.github.io/TRENDcreate-Benchmark/

みんなのスコアをランキング表示し、自分の `score/*.json` を貼り付けてその場で比較できます。
投稿は `score/` にJSONを追加 → `python tools/build_pages.py` で `docs/data.json` とローカル用 `summary.html` を生成 → Pull Request、または Issue にJSONを貼るだけ。

## 構成

| ファイル | OS | 役割 |
|---|---|---|
| `Tc_bench.py` | 共通 | ベンチマーク実行 / スコア集計・ランキング表示 |
| `score/` | 共通 | スコアJSONの保存先（自動生成） |
| `tools/build_pages.py` | 共通 | `score/*.json` から `docs/data.json` と `summary.html` を生成 |
| `summary.html` | 共通 | ローカルで開ける単体HTMLのスコア一覧（生成物） |

## 必要環境

- **Python 3.6+**（`multiprocessing`, `math`, `json` など標準ライブラリのみ使用）
- Linux: `lscpu`（システム情報取得）、GPU情報は `nvidia-smi`（NVIDIA）/ `amdgpu` の sysfs・`rocm-smi`・`lspci`（AMD）
- macOS: `sysctl` / `system_profiler`（標準搭載）
- Windows: PowerShell（標準搭載）、GPU情報は `nvidia-smi`（NVIDIA）/ WMI + レジストリ（AMD）

## 使い方

### ベンチマーク実行

**Linux / macOS（ワンライナー / クローン不要）**
```bash
curl -fsSL https://raw.githubusercontent.com/trendcreate/TRENDcreate-Benchmark/main/Tc_bench.py -o Tc_bench.py && python3 Tc_bench.py
```
スコアは `Tc_bench.py` を置いたディレクトリの `./score/` に保存されます。

**Linux / macOS（クローン済みの場合）**
```bash
python3 Tc_bench.py
```

**Windows**
```powershell
py Tc_bench.py
# または
python Tc_bench.py
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
6. **ローカルHTML生成** — `tools/build_pages.py` を呼び出して `summary.html` を生成し、対話可能な端末ではブラウザで開くか確認

`summary.html` を確認なしで開く場合は `--open-summary`、生成を省略する場合は `--no-summary` を指定できます。

### スコア集計・ランキング

`score/` 内の全結果を読み込み、組み合わせごとのベストスコアをランキング表示します。

**Linux / macOS**
```bash
python3 Tc_bench.py summary                 # マルチスコア順（既定）
python3 Tc_bench.py summary --sort single   # シングル順
python3 Tc_bench.py summary --sort gpu      # GPU V-Calc順
```

**Windows**
```powershell
py Tc_bench.py summary                 # マルチスコア順（既定）
py Tc_bench.py summary --sort single   # シングル順
py Tc_bench.py summary --sort gpu      # GPU V-Calc順
```

### ローカルHTMLの再生成

`summary.html` は `score/*.json` を埋め込んだ単体HTMLです。ブラウザで直接開けるため、`docs/data.json` を読む GitHub Pages なしでもランキングを確認できます。

```bash
python tools/build_pages.py
```

ベンチ完了後のブラウザ起動は、`BROWSER` 環境変数を優先し、Windows は既定の関連付け、macOS は `open`、Linux は `xdg-open` などOS標準の方法を使います。

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

- `multiprocessing` を使うため、ワンライナーでも `Tc_bench.py` をファイルとして保存してから実行してください（標準入力からの実行は非推奨）。
- Windows で文字化けする場合: Windows Terminal / PowerShell を使い、必要に応じて `chcp 65001` を実行してください。
- スコアの負荷量は `--work-limit`（既定 `600000`）または環境変数 `TC_BENCH_WORK_LIMIT` で調整できます。低速マシンで時間がかかりすぎる場合は小さくしてください。
- 集計時に壊れた / 0バイトの JSON があっても、自動的にスキップして「スキップ: N」と表示します（クラッシュしません）。
- `summary.html` は生成物のため `.gitignore` 対象です。共有ページへの反映には従来どおり `docs/data.json` と `score/*.json` を使います。

## スコアの算出式（参考）

```
CPU Single = 10000 / シングル実行秒数
CPU Multi  = 10000 × 論理スレッド数 / マルチ実行秒数
GPU V-Calc = 最大クロック(MHz) × (VRAM_GB ^ 1.5) / 10   (クロック不明時は公称 1500MHz)
```

スコアは相対比較用の独自指標です。CPU負荷状態（他プロセス・電源/温度による周波数制御）で変動するため、計測はアイドル状態で行うことを推奨します。
