#!/usr/bin/env python3
"""Issue 本文に貼られた score JSON を取り込んで score/<combo>.json に保存する。

GitHub Actions から呼び出す。環境変数:
  ISSUE_BODY    : Issue 本文
出力(GITHUB_OUTPUT へ): status=ok|skip|error, combo, message
"""
import os, re, json, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORE_DIR = os.path.join(ROOT, "score")

def out(**kv):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")
    for k, v in kv.items():
        print(f"[ingest] {k}={v}")

def slug(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "").strip())
    s = s.strip("._-")
    return s or "unknown"

def extract_json(body):
    if not body:
        raise ValueError("Issue 本文が空です")
    # ```json ... ``` を優先、無ければ ``` ... ```、最後に最初の { から最後の } まで
    m = re.search(r"```json\s*(.+?)```", body, re.S | re.I)
    if not m:
        m = re.search(r"```\s*(\{.+?\})\s*```", body, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        s, e = body.find("{"), body.rfind("}")
        if s == -1 or e == -1 or e < s:
            raise ValueError("JSON コードブロックが見つかりません")
        raw = body[s:e+1]
    return json.loads(raw)

def num_or_none(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def normalize(d):
    si = d.get("system") or {}
    best = d.get("best") or {}
    runs = d.get("runs") or []
    # best が無い場合は最新 run の scores から拾う
    if not best and runs:
        best = (runs[-1] or {}).get("scores", {}) or {}
    rec_best = {
        "cpu_single": num_or_none(best.get("cpu_single")),
        "cpu_multi":  num_or_none(best.get("cpu_multi")),
        "gpu_vcalc":  num_or_none(best.get("gpu_vcalc")),
        "gpu_diffusion": num_or_none(best.get("gpu_diffusion")),
        "multi_ratio": num_or_none(best.get("multi_ratio")),
    }
    if rec_best["cpu_single"] is None and rec_best["cpu_multi"] is None:
        raise ValueError("有効なスコア(cpu_single / cpu_multi)がありません")
    system = {
        "cpu_model": str(si.get("cpu_model") or "Unknown")[:200],
        "architecture": (str(si.get("architecture"))[:60] if si.get("architecture") else None),
        "cores_per_socket": (str(si.get("cores_per_socket"))[:20] if si.get("cores_per_socket") is not None else None),
        "logical_processors": si.get("logical_processors") if isinstance(si.get("logical_processors"), int) else None,
        "cpu_mhz": num_or_none(si.get("cpu_mhz")),
        "l3_cache": (str(si.get("l3_cache"))[:40] if si.get("l3_cache") else None),
        "gpu_name": (str(si.get("gpu_name"))[:120] if si.get("gpu_name") else None),
        "gpu_vram_mb": num_or_none(si.get("gpu_vram_mb")),
        "gpu_sm_clock_mhz": num_or_none(si.get("gpu_sm_clock_mhz")),
    }
    combo = d.get("combo") or f"{slug(system['cpu_model'])}__{slug(system['gpu_name'] or 'N_A')}"
    combo = slug(combo)[:160]
    return combo, system, rec_best

def main():
    try:
        body = os.environ.get("ISSUE_BODY", "")
        if len(body) > 200000:
            raise ValueError("本文が大きすぎます")
        d = extract_json(body)
        combo, system, new_best = normalize(d)
    except Exception as e:
        out(status="error", combo="", message=str(e))
        return

    os.makedirs(SCORE_DIR, exist_ok=True)
    path = os.path.join(SCORE_DIR, combo + ".json")
    # 念のためパストラバーサル防止
    if os.path.commonpath([os.path.abspath(path), os.path.abspath(SCORE_DIR)]) != os.path.abspath(SCORE_DIR):
        out(status="error", combo="", message="不正なファイル名")
        return

    data = {"combo": combo, "system": system, "best": {}, "runs": []}
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("best", {}); data.setdefault("runs", [])
        except Exception:
            pass

    # best を更新 (大きいほど良い)
    for k, v in new_best.items():
        if v is None:
            continue
        if data["best"].get(k) is None or v > data["best"][k]:
            data["best"][k] = v
    data["system"] = system
    data["combo"] = combo
    # 受領記録を runs に追加 (Issue 経由であることを明示)
    import datetime
    data["runs"].append({
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "source": "issue",
        "scores": new_best,
    })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    out(status="ok", combo=combo,
        message=f"{system['cpu_model']} / {system['gpu_name'] or '-'} を取り込みました")

if __name__ == "__main__":
    main()
