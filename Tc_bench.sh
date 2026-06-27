#!/usr/bin/env bash
#
# Tc_bench.sh - TC Bench CPU/GPU ベンチマーク兼システム診断ツール
#               (Lubuntu / antiX / 一般的なLinux 向け / 標準ライブラリのみ)
#
set -u

# ============================================================================
#  カラー定義 (ANSI)
# ============================================================================
if [ -t 1 ]; then
    C_RESET="\033[0m";  C_BOLD="\033[1m"
    C_RED="\033[31m";   C_GREEN="\033[32m"; C_YELLOW="\033[33m"
    C_BLUE="\033[34m";  C_MAGENTA="\033[35m"; C_CYAN="\033[36m"
else
    C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_MAGENTA=""; C_CYAN=""
fi

# ============================================================================
#  lscpu ヘルパ (英語/日本語ロケール両対応)
# ============================================================================
# スクリプト自身の場所と score/ ディレクトリ
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SCORE_DIR="$SELF_DIR/score"
mkdir -p "$SCORE_DIR" 2>/dev/null

get_lscpu() {
    lscpu 2>/dev/null | grep -E "^($1):" | head -n1 | sed -E 's/^[^:]+:[[:space:]]*//'
}

CPU_MODEL="$(get_lscpu 'Model name|モデル名')";            [ -z "$CPU_MODEL" ] && CPU_MODEL="不明 (Unknown)"
ARCH="$(get_lscpu 'Architecture|アーキテクチャ')";         [ -z "$ARCH" ] && ARCH="$(uname -m)"
CORES="$(get_lscpu 'Core\(s\) per socket|ソケットあたりのコア数')"
TPC="$(get_lscpu 'Thread\(s\) per core|コアあたりのスレッド数')"
L3_CACHE="$(get_lscpu 'L3 cache|L3 キャッシュ')";          [ -z "$L3_CACHE" ] && L3_CACHE="N/A"
NPROC="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"

# ============================================================================
#  GPU情報の取得 (NVIDIA / AMD 対応)
# ============================================================================
GPU_NAME="N/A"; GPU_VRAM_MB="0"; GPU_SMCLK_MHZ="0"; HAS_GPU="0"; GPU_VENDOR=""

# --- NVIDIA (nvidia-smi) ---
if command -v nvidia-smi >/dev/null 2>&1; then
    _gpuline="$(nvidia-smi --query-gpu=name,memory.total,clocks.max.sm \
                --format=csv,noheader,nounits 2>/dev/null | head -n1)"
    if [ -n "$_gpuline" ]; then
        HAS_GPU="1"; GPU_VENDOR="NVIDIA"
        GPU_NAME="$(echo "$_gpuline"   | awk -F',' '{gsub(/^[ \t]+|[ \t]+$/,"",$1); print $1}')"
        GPU_VRAM_MB="$(echo "$_gpuline" | awk -F',' '{gsub(/[^0-9]/,"",$2); print $2}')"
        GPU_SMCLK_MHZ="$(echo "$_gpuline" | awk -F',' '{gsub(/[^0-9]/,"",$3); print $3}')"
        [ -z "$GPU_VRAM_MB" ]   && GPU_VRAM_MB="0"
        [ -z "$GPU_SMCLK_MHZ" ] && GPU_SMCLK_MHZ="0"
    fi
fi

# --- AMD (rocm-smi があれば優先) ---
if [ "$HAS_GPU" = "0" ] && command -v rocm-smi >/dev/null 2>&1; then
    _amdname="$(rocm-smi --showproductname 2>/dev/null | grep -iE 'Card series|Card model|Product Name' | head -n1 | sed -E 's/.*:[[:space:]]*//')"
    _amdvram="$(rocm-smi --showmeminfo vram 2>/dev/null | grep -iE 'Total' | head -n1 | grep -oE '[0-9]+' | head -n1)"  # bytes
    _amdclk="$(rocm-smi --showmaxclocks 2>/dev/null | grep -iE 'sclk' | grep -oE '[0-9]+' | head -n1)"
    if [ -n "$_amdname" ] || [ -n "$_amdvram" ]; then
        HAS_GPU="1"; GPU_VENDOR="AMD"
        GPU_NAME="${_amdname:-AMD GPU}"
        [ -n "$_amdvram" ] && GPU_VRAM_MB="$(( _amdvram / 1048576 ))"
        [ -n "$_amdclk" ]  && GPU_SMCLK_MHZ="$_amdclk"
    fi
fi

# --- AMD (amdgpu の sysfs から取得 / 追加ツール不要) ---
if [ "$HAS_GPU" = "0" ]; then
    for _dev in /sys/class/drm/card[0-9]*/device; do
        [ -e "$_dev/mem_info_vram_total" ] || continue
        _vendor_id="$(cat "$_dev/vendor" 2>/dev/null)"
        [ "$_vendor_id" = "0x1002" ] || continue          # 0x1002 = AMD
        HAS_GPU="1"; GPU_VENDOR="AMD"
        _bytes="$(cat "$_dev/mem_info_vram_total" 2>/dev/null)"
        [ -n "$_bytes" ] && GPU_VRAM_MB="$(( _bytes / 1048576 ))"
        # 最大sclk (pp_dpm_sclk の最終行の MHz)
        if [ -e "$_dev/pp_dpm_sclk" ]; then
            GPU_SMCLK_MHZ="$(grep -oE '[0-9]+Mhz' "$_dev/pp_dpm_sclk" | grep -oE '[0-9]+' | sort -n | tail -n1)"
            [ -z "$GPU_SMCLK_MHZ" ] && GPU_SMCLK_MHZ="0"
        fi
        # 名前は lspci から
        if command -v lspci >/dev/null 2>&1; then
            GPU_NAME="$(lspci 2>/dev/null | grep -iE 'VGA|3D|Display' | grep -iE 'AMD|ATI|Radeon' | head -n1 | sed -E 's/.*: //')"
        fi
        [ -z "$GPU_NAME" ] && GPU_NAME="AMD GPU"
        break
    done
fi

# --- 名前だけでも lspci で AMD を拾う (VRAM不明でも検出) ---
if [ "$HAS_GPU" = "0" ] && command -v lspci >/dev/null 2>&1; then
    _line="$(lspci 2>/dev/null | grep -iE 'VGA|3D|Display' | grep -iE 'AMD|ATI|Radeon' | head -n1)"
    if [ -n "$_line" ]; then
        HAS_GPU="1"; GPU_VENDOR="AMD"
        GPU_NAME="$(echo "$_line" | sed -E 's/.*: //')"
        # glxinfo があれば VRAM を取得
        if command -v glxinfo >/dev/null 2>&1; then
            GPU_VRAM_MB="$(glxinfo 2>/dev/null | grep -iE 'Video memory|Dedicated video memory' | grep -oE '[0-9]+' | head -n1)"
            [ -z "$GPU_VRAM_MB" ] && GPU_VRAM_MB="0"
        fi
    fi
fi

# --- AMD: VRAM/クロックの後追い補完 (どの検出経路でも実行) ---
# 名前だけ取れて VRAM=0 になるケース(rocm-smi等)を amdgpu の sysfs で救済する。
if [ "$HAS_GPU" = "1" ] && { [ "${GPU_VRAM_MB:-0}" = "0" ] || [ "${GPU_SMCLK_MHZ:-0}" = "0" ]; }; then
    for _dev in /sys/class/drm/card[0-9]*/device; do
        [ -e "$_dev/vendor" ] || continue
        [ "$(cat "$_dev/vendor" 2>/dev/null)" = "0x1002" ] || continue
        if [ "${GPU_VRAM_MB:-0}" = "0" ] && [ -r "$_dev/mem_info_vram_total" ]; then
            _b="$(cat "$_dev/mem_info_vram_total" 2>/dev/null)"
            if [ -n "$_b" ] && [ "$_b" -gt 0 ] 2>/dev/null; then
                GPU_VRAM_MB="$(( _b / 1048576 ))"
            fi
        fi
        if [ "${GPU_SMCLK_MHZ:-0}" = "0" ] && [ -r "$_dev/pp_dpm_sclk" ]; then
            _c="$(grep -oiE '[0-9]+[[:space:]]*mhz' "$_dev/pp_dpm_sclk" 2>/dev/null | grep -oE '[0-9]+' | sort -n | tail -n1)"
            [ -n "$_c" ] && GPU_SMCLK_MHZ="$_c"
        fi
        [ "${GPU_VRAM_MB:-0}" != "0" ] && break
    done
fi

# --- 最後の砦: lspci の prefetchable BAR サイズから VRAM を推定 ---
if [ "$HAS_GPU" = "1" ] && [ "${GPU_VRAM_MB:-0}" = "0" ] && command -v lspci >/dev/null 2>&1; then
    _bar="$(lspci -v 2>/dev/null | awk '/VGA|3D|Display/{f=1} f&&/prefetchable/{print; } /^$/{f=0}' \
            | grep -oiE 'size=[0-9]+[MG]' | head -n1)"
    if [ -n "$_bar" ]; then
        _val="$(echo "$_bar" | grep -oE '[0-9]+')"
        case "$_bar" in
            *G|*g) GPU_VRAM_MB="$(( _val * 1024 ))" ;;
            *M|*m) GPU_VRAM_MB="$_val" ;;
        esac
    fi
fi

# ============================================================================
#  ヘッダ & システム情報表示
# ============================================================================
clear 2>/dev/null
echo -e "${C_CYAN}${C_BOLD}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║   ▀█▀ █▀▀   █▄▄ █▀▀ █▄ █ █▀▀ █ █  CPU / GPU Benchmark    ║"
echo "  ║    █  █▄▄   █▄█ ██▄ █ ▀█ █▄▄ █▀█  CPU / GPU  v1.0        ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${C_RESET}"

echo -e "${C_BOLD}${C_YELLOW}  ── システム情報 (System Information) ──${C_RESET}"
printf "  ${C_GREEN}%-20s${C_RESET}: ${C_BOLD}%s${C_RESET}\n" "CPUモデル名"       "$CPU_MODEL"
printf "  ${C_GREEN}%-20s${C_RESET}: ${C_BOLD}%s${C_RESET}\n" "アーキテクチャ"   "$ARCH"
printf "  ${C_GREEN}%-20s${C_RESET}: ${C_BOLD}%s / %s${C_RESET}\n" "コア数 / スレッド数" "${CORES:-N/A} cores" "$NPROC threads"
printf "  ${C_GREEN}%-20s${C_RESET}: ${C_BOLD}%s${C_RESET}\n" "L3キャッシュ容量" "$L3_CACHE"
if [ "$HAS_GPU" = "1" ]; then
    printf "  ${C_GREEN}%-20s${C_RESET}: ${C_BOLD}%s (%s)${C_RESET}\n" "GPUモデル名" "$GPU_NAME" "$GPU_VENDOR"
    if [ "$GPU_SMCLK_MHZ" != "0" ]; then
        printf "  ${C_GREEN}%-20s${C_RESET}: ${C_BOLD}%s MB (最大クロック %s MHz)${C_RESET}\n" "VRAM総容量" "$GPU_VRAM_MB" "$GPU_SMCLK_MHZ"
    else
        printf "  ${C_GREEN}%-20s${C_RESET}: ${C_BOLD}%s MB${C_RESET} ${C_YELLOW}(クロック不明→公称値で算出)${C_RESET}\n" "VRAM総容量" "$GPU_VRAM_MB"
    fi
else
    printf "  ${C_GREEN}%-20s${C_RESET}: ${C_YELLOW}%s${C_RESET}\n" "GPU" "NVIDIA/AMD 未検出 — GPUスコアはスキップ (OOM回避モード)"
fi
echo ""

# ============================================================================
#  Python3 確認
# ============================================================================
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo -e "${C_RED}${C_BOLD}エラー: python3 が見つかりません。${C_RESET}  Debian系: ${C_CYAN}sudo apt install python3${C_RESET}"
    exit 1
fi

# 保存済みスコア一覧
_saved="$(ls -1 "$SCORE_DIR"/*.json 2>/dev/null)"
if [ -n "$_saved" ]; then
    echo -e "${C_BOLD}${C_YELLOW}  ── 保存済みスコア (score/) ──${C_RESET}"
    for f in "$SCORE_DIR"/*.json; do
        [ -e "$f" ] || continue
        printf "  ${C_CYAN}•${C_RESET} %s\n" "$(basename "$f")"
    done
    echo ""
fi

echo -e "${C_BOLD}${C_MAGENTA}  ── ベンチマーク実行中 (全スレッド100%%で負荷をかけます) ──${C_RESET}"
echo ""

# ============================================================================
#  ベンチマーク本体 (インラインPython3 / 標準ライブラリのみ)
#    引数: NPROC  HAS_GPU  GPU_VRAM_MB  GPU_SMCLK_MHZ  CPU_MODEL  GPU_NAME  SCORE_DIR  ARCH  CORES  L3  GPU_VENDOR
# ============================================================================
"$PY" - "$NPROC" "$HAS_GPU" "$GPU_VRAM_MB" "$GPU_SMCLK_MHZ" "$CPU_MODEL" "$GPU_NAME" "$SCORE_DIR" "$ARCH" "${CORES:-N/A}" "$L3_CACHE" "$GPU_VENDOR" <<'PYEOF'
import sys, time, math, os, json, re, platform
from datetime import datetime, timezone
import multiprocessing as _mp
from multiprocessing import Pool, cpu_count

# Python 3.14 以降 Linux の既定が forkserver になり、stdin(ヒアドキュメント)実行だと
# __main__ を再import できず失敗する。fork に固定して回避する。
try:
    if "fork" in _mp.get_all_start_methods():
        _mp.set_start_method("fork", force=True)
except Exception:
    pass

C_RESET="\033[0m"; C_BOLD="\033[1m"; C_GREEN="\033[32m"
C_YELLOW="\033[33m"; C_CYAN="\033[36m"; C_MAGENTA="\033[35m"; C_RED="\033[31m"

NPROC      = int(sys.argv[1]) if len(sys.argv) > 1 else cpu_count()
HAS_GPU    = sys.argv[2] == "1" if len(sys.argv) > 2 else False
GPU_VRAM   = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0   # MB
GPU_SMCLK  = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0   # MHz
CPU_MODEL  = sys.argv[5] if len(sys.argv) > 5 else "Unknown"
GPU_NAME   = sys.argv[6] if len(sys.argv) > 6 else "N/A"
SCORE_DIR  = sys.argv[7] if len(sys.argv) > 7 else "score"
ARCH       = sys.argv[8] if len(sys.argv) > 8 else ""
CORES      = sys.argv[9] if len(sys.argv) > 9 else ""
L3_CACHE   = sys.argv[10] if len(sys.argv) > 10 else ""
GPU_VENDOR = sys.argv[11] if len(sys.argv) > 11 else ""

# --- 計算ワークロード: 素数判定 + 重い浮動小数点演算でCPU100%張り付き ---
WORK_LIMIT = 600000
def heavy_work(limit):
    count = 0; acc = 0.0; n = 2
    while n < limit:
        is_prime = True; r = int(math.isqrt(n)); d = 2
        while d <= r:
            if n % d == 0:
                is_prime = False; break
            d += 1
        if is_prime:
            count += 1
            acc += math.sqrt(n) * math.sin(n) + math.log(n + 1)
        n += 1
    return (count, acc)

def run_pool(workers, tasks):
    start = time.perf_counter()
    with Pool(processes=workers) as pool:
        pool.map(heavy_work, [WORK_LIMIT] * tasks)
    return time.perf_counter() - start

# --- ASCIIバーチャート ---
def bar(score, max_score, width=40):
    if max_score <= 0: max_score = 1
    filled = int(round((score / max_score) * width))
    filled = max(0, min(width, filled))
    return "[" + "■" * filled + "." * (width - filled) + "]"

# ===== 計測 =================================================================
print(f"  {C_CYAN}[1/2] シングルスレッド性能テスト 実行中...{C_RESET}", flush=True)
single_time = run_pool(1, 1)
print(f"        {C_GREEN}完了: {single_time:.2f} 秒{C_RESET}\n", flush=True)

print(f"  {C_CYAN}[2/2] マルチスレッド性能テスト ({NPROC} スレッド) 実行中...{C_RESET}", flush=True)
multi_time = run_pool(NPROC, NPROC)
print(f"        {C_GREEN}完了: {multi_time:.2f} 秒{C_RESET}\n", flush=True)

# ===== スコア算出 ===========================================================
SCORE_FACTOR = 10000.0
single_score = SCORE_FACTOR / single_time
multi_score  = (SCORE_FACTOR * NPROC) / multi_time
ratio        = single_time / multi_time if multi_time > 0 else 0.0

# GPU V-Calcスコア: (最大クロック × VRAM容量) ベース。VRAMを圧倒的に優遇。
# NVIDIA / AMD 両対応。クロック不明(AMD等)の場合は公称値で算出する。
NOMINAL_CLK = 1500.0
gpu_score = 0.0
gpu_estimated = False
if HAS_GPU and GPU_VRAM > 0:
    vram_gb = GPU_VRAM / 1024.0
    clk = GPU_SMCLK if GPU_SMCLK > 0 else NOMINAL_CLK
    if GPU_SMCLK <= 0:
        gpu_estimated = True
    # VRAMの「暴力」: 容量に対して指数的にスコアが伸びるロマン仕様 (vram_gb^1.5)
    gpu_score = (clk * (vram_gb ** 1.5)) / 10.0

# ===== 結果出力 (レトロサイバーパンク風) ====================================
print(f"{C_BOLD}{C_MAGENTA}  ╔══════════════════════════════════════════════════════════════════╗{C_RESET}")
print(f"{C_BOLD}{C_MAGENTA}  ║                  >> BENCHMARK  RESULT  SCORE <<                   ║{C_RESET}")
print(f"{C_BOLD}{C_MAGENTA}  ╚══════════════════════════════════════════════════════════════════╝{C_RESET}")

scores = [single_score, multi_score] + ([gpu_score] if gpu_score > 0 else [])
max_score = max(scores) if scores else 1.0

print(f"  {C_YELLOW}CPU Single{C_RESET} {C_GREEN}{bar(single_score, max_score)}{C_RESET} "
      f"{C_BOLD}{single_score:7.0f} pts{C_RESET} {C_CYAN}(優しさの証){C_RESET}")
print(f"  {C_YELLOW}CPU Multi {C_RESET} {C_GREEN}{bar(multi_score, max_score)}{C_RESET} "
      f"{C_BOLD}{multi_score:7.0f} pts{C_RESET} {C_CYAN}(全スレッド全力回転){C_RESET}")

if gpu_score > 0:
    _note = "(VRAM暴力の真価)" + (" ※クロック公称値" if gpu_estimated else "")
    _vd = f"[{GPU_VENDOR}]" if GPU_VENDOR else ""
    print(f"  {C_YELLOW}GPU V-Calc{C_RESET} {C_MAGENTA}{bar(gpu_score, max_score)}{C_RESET} "
          f"{C_BOLD}{gpu_score:7.0f} pts{C_RESET} {C_CYAN}{_note}{C_RESET} {C_MAGENTA}{_vd}{C_RESET}")
else:
    print(f"  {C_YELLOW}GPU V-Calc{C_RESET} {C_RED}[..........................................]   SKIPPED{C_RESET} "
          f"{C_CYAN}(NVIDIA/AMD未検出 / OOM回避){C_RESET}")

print(f"{C_BOLD}{C_MAGENTA}  ────────────────────────────────────────────────────────────────────{C_RESET}")
print(f"  {C_YELLOW}マルチコア倍率{C_RESET} : {C_BOLD}{ratio:.2f}x{C_RESET}  "
      f"({C_GREEN}Single {single_time:.2f}s{C_RESET} / {C_GREEN}Multi {multi_time:.2f}s{C_RESET})")

# ===== スコアのJSON保存 / 過去スコア比較 ====================================
def slug(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "").strip())
    return s.strip("_") or "unknown"

combo = f"{slug(CPU_MODEL)}__{slug(GPU_NAME)}"
path  = os.path.join(SCORE_DIR, combo + ".json")

record = {
    "schema": "tc_bench/score/v1",
    "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "os": platform.platform(),
    "system": {
        "cpu_model": CPU_MODEL, "architecture": ARCH,
        "cores_per_socket": CORES, "logical_processors": NPROC,
        "l3_cache": L3_CACHE,
        "gpu_name": GPU_NAME if HAS_GPU else None,
        "gpu_vendor": GPU_VENDOR if HAS_GPU else None,
        "gpu_vram_mb": GPU_VRAM if HAS_GPU else None,
        "gpu_sm_clock_mhz": (GPU_SMCLK if (HAS_GPU and GPU_SMCLK > 0) else None),
    },
    "scores": {
        "cpu_single": round(single_score, 1),
        "cpu_multi":  round(multi_score, 1),
        "gpu_vcalc":  round(gpu_score, 1) if gpu_score > 0 else None,
        "multi_ratio": round(ratio, 2),
        "single_time_s": round(single_time, 3),
        "multi_time_s":  round(multi_time, 3),
    },
}

# 既存ファイルは履歴(runs)として追記し、ベストスコアも記録
data = {"combo": combo, "system": record["system"], "best": {}, "runs": []}
if os.path.exists(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("runs", []); data.setdefault("best", {})
    except Exception:
        pass

# 今回の結果と過去ベストを比較表示
prev_best = data.get("best", {})
def cmp_line(label, key, cur):
    if cur is None: return
    pb = prev_best.get(key)
    if pb is None:
        tag = f"{C_GREEN}NEW{C_RESET}"
    elif cur >= pb:
        tag = f"{C_GREEN}▲ ベスト更新! (旧 {pb:.0f}){C_RESET}"
    else:
        tag = f"{C_YELLOW}過去ベスト {pb:.0f}{C_RESET}"
    print(f"  {C_CYAN}{label:<12}{C_RESET}: {cur:7.0f} pts  {tag}")

print(f"{C_BOLD}{C_MAGENTA}  ── 過去スコアとの比較 ({combo}) ──{C_RESET}")
cmp_line("CPU Single", "cpu_single", single_score)
cmp_line("CPU Multi",  "cpu_multi",  multi_score)
if gpu_score > 0:
    cmp_line("GPU V-Calc", "gpu_vcalc", gpu_score)

# best 更新 (大きいほど良い)
for k, v in record["scores"].items():
    if v is None or k in ("single_time_s", "multi_time_s"): continue
    if data["best"].get(k) is None or v > data["best"][k]:
        data["best"][k] = v
data["system"] = record["system"]
data["runs"].append(record)

try:
    # 一時ファイルに書き切ってから差し替える(中断しても空/壊れファイルを残さない)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    print(f"  {C_GREEN}スコアを保存しました:{C_RESET} {path}")
    print(f"  {C_CYAN}(このJSONファイルを共有すれば結果を比較できます){C_RESET}")
except Exception as e:
    try:
        if os.path.exists(tmp): os.remove(tmp)
    except Exception:
        pass
    print(f"  {C_RED}スコア保存に失敗: {e}{C_RESET}")
PYEOF

echo ""
echo -e "${C_GREEN}${C_BOLD}  ベンチマーク完了。お疲れ様でした！${C_RESET}"

# ============================================================================
#  即時実行の自動化: 自身に実行権限を付与
# ============================================================================
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
if [ ! -x "$SELF" ]; then
    chmod +x "$SELF" 2>/dev/null \
        && echo -e "  ${C_CYAN}(自身に実行権限を付与しました: ./$(basename "$0") で再実行できます)${C_RESET}"
fi
