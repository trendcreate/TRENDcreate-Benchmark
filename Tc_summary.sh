#!/usr/bin/env bash
#
# Tc_summary.sh - TC Bench スコア集計ツール (Linux)
#   score/ 内の *.json を読み込み、ベストスコアを一覧・ランキング表示します。
#
set -u

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SCORE_DIR="$SELF_DIR/score"

if [ -t 1 ]; then
    C_RESET="\033[0m"; C_BOLD="\033[1m"; C_GREEN="\033[32m"
    C_YELLOW="\033[33m"; C_CYAN="\033[36m"; C_MAGENTA="\033[35m"; C_RED="\033[31m"
else
    C_RESET=""; C_BOLD=""; C_GREEN=""; C_YELLOW=""; C_CYAN=""; C_MAGENTA=""; C_RED=""
fi

if [ ! -d "$SCORE_DIR" ]; then
    echo -e "${C_RED}score/ フォルダが見つかりません: $SCORE_DIR${C_RESET}"
    exit 1
fi

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo -e "${C_RED}python3 が見つかりません。${C_RESET}"
    exit 1
fi

# 引数: --sort=single|multi|gpu  (省略時 multi)
SORT_KEY="multi"
for a in "$@"; do
    case "$a" in
        --sort=*) SORT_KEY="${a#--sort=}" ;;
    esac
done

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
"$PY" - "$SCORE_DIR" "$SORT_KEY" <<'PYEOF'
import sys, os, json, glob

C_RESET="\033[0m"; C_BOLD="\033[1m"; C_GREEN="\033[32m"
C_YELLOW="\033[33m"; C_CYAN="\033[36m"; C_MAGENTA="\033[35m"; C_RED="\033[31m"

SCORE_DIR = sys.argv[1]
SORT_KEY  = sys.argv[2] if len(sys.argv) > 2 else "multi"
KEYMAP = {"single": "cpu_single", "multi": "cpu_multi", "gpu": "gpu_vcalc"}
sort_field = KEYMAP.get(SORT_KEY, "cpu_multi")

rows = []
skipped = 0
for path in sorted(glob.glob(os.path.join(SCORE_DIR, "*.json"))):
    try:
        if os.path.getsize(path) == 0:
            skipped += 1; continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        skipped += 1; continue
    sysinfo = data.get("system", {})
    best    = data.get("best", {})
    runs    = data.get("runs", [])
    rows.append({
        "cpu":    sysinfo.get("cpu_model") or "Unknown",
        "gpu":    sysinfo.get("gpu_name") or "-",
        "single": best.get("cpu_single"),
        "multi":  best.get("cpu_multi"),
        "gpu_v":  best.get("gpu_vcalc"),
        "runs":   len(runs),
        "file":   os.path.basename(path),
    })

if not rows:
    print(f"{C_YELLOW}集計対象のスコアがありません。先に Tc_bench を実行してください。{C_RESET}")
    sys.exit(0)

best_field_key = {"cpu_single":"single","cpu_multi":"multi","gpu_vcalc":"gpu_v"}[sort_field]
rows.sort(key=lambda r: (r[best_field_key] is None, -(r[best_field_key] or 0)))

def fmt(v):
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "-"

print(f"{C_BOLD}{C_CYAN}")
print("  ╔══════════════════════════════════════════════════════════════════╗")
print("  ║                  TC BENCH  スコア集計 / ランキング                ║")
print("  ╚══════════════════════════════════════════════════════════════════╝")
print(f"{C_RESET}")
_skip = f"  |  {C_RED}スキップ:{C_RESET} {skipped}" if skipped else ""
print(f"  {C_YELLOW}並び順:{C_RESET} {SORT_KEY}  |  {C_YELLOW}登録数:{C_RESET} {len(rows)} 組み合わせ{_skip}\n")

hdr = f"  {C_BOLD}{'#':>2}  {'CPU':<34}{'GPU':<22}{'Single':>8}{'Multi':>9}{'GPU-V':>9}{'Runs':>6}{C_RESET}"
print(hdr)
print("  " + "─" * 88)
for i, r in enumerate(rows, 1):
    cpu = (r["cpu"][:32] + "..") if len(r["cpu"]) > 34 else r["cpu"]
    gpu = (r["gpu"][:20] + "..") if len(r["gpu"]) > 22 else r["gpu"]
    medal = {1:"🥇",2:"🥈",3:"🥉"}.get(i, f"{i}")
    line = (f"  {medal:>2}  {C_BOLD}{cpu:<34}{C_RESET}{C_CYAN}{gpu:<22}{C_RESET}"
            f"{C_GREEN}{fmt(r['single']):>8}{C_RESET}"
            f"{C_GREEN}{fmt(r['multi']):>9}{C_RESET}"
            f"{C_MAGENTA}{fmt(r['gpu_v']):>9}{C_RESET}"
            f"{C_YELLOW}{r['runs']:>6}{C_RESET}")
    print(line)
print("  " + "─" * 88)
print(f"  {C_CYAN}※ 各値は組み合わせごとのベストスコア。並び替え: ./Tc_summary.sh --sort=single|multi|gpu{C_RESET}")
PYEOF
