#!/usr/bin/env python3
"""score/*.json を集計して docs/data.json を生成する。

GitHub Pages は静的配信のためディレクトリ一覧を取得できない。
そこで全スコアを1つの data.json にまとめてページから読み込めるようにする。

使い方:  python tools/build_pages.py
"""
import os, json, glob, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORE_DIR = os.path.join(ROOT, "score")
OUT = os.path.join(ROOT, "docs", "data.json")

entries = []
for path in sorted(glob.glob(os.path.join(SCORE_DIR, "*.json"))):
    if os.path.getsize(path) == 0:
        continue
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        continue
    si = data.get("system", {})
    best = data.get("best", {})
    runs = data.get("runs", [])
    last_ts = runs[-1].get("timestamp") if runs else None
    entries.append({
        "combo": data.get("combo") or os.path.splitext(os.path.basename(path))[0],
        "cpu": si.get("cpu_model") or "Unknown",
        "gpu": si.get("gpu_name"),
        "arch": si.get("architecture"),
        "cores": si.get("cores_per_socket"),
        "threads": si.get("logical_processors"),
        "l3": si.get("l3_cache"),
        "vram_mb": si.get("gpu_vram_mb"),
        "single": best.get("cpu_single"),
        "multi": best.get("cpu_multi"),
        "gpu_vcalc": best.get("gpu_vcalc"),
        "runs": len(runs),
        "last": last_ts,
    })

out = {
    "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "count": len(entries),
    "entries": entries,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"wrote {OUT} ({len(entries)} entries)")
