#!/usr/bin/env python3
"""score/*.json を集計して docs/data.json と summary.html を生成する。

GitHub Pages は静的配信のためディレクトリ一覧を取得できない。
そこで全スコアを1つの data.json にまとめてページから読み込めるようにする。
summary.html はローカル確認用の単体HTMLとして、同じデータを埋め込んで生成する。

使い方:  python tools/build_pages.py
"""
import datetime
import glob
import html
import json
import os


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORE_DIR = os.path.join(ROOT, "score")
DATA_OUT = os.path.join(ROOT, "docs", "data.json")
SUMMARY_OUT = os.path.join(ROOT, "summary.html")


def collect_entries(score_dir=SCORE_DIR):
    entries = []
    for path in sorted(glob.glob(os.path.join(score_dir, "*.json"))):
        try:
            if os.path.getsize(path) == 0:
                continue
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
            "cpu_mhz": si.get("cpu_mhz"),
            "l3": si.get("l3_cache"),
            "vram_mb": si.get("gpu_vram_mb"),
            "single": best.get("cpu_single"),
            "multi": best.get("cpu_multi"),
            "gpu_vcalc": best.get("gpu_vcalc"),
            "gpu_diffusion": best.get("gpu_diffusion"),
            "runs": len(runs),
            "last": last_ts,
        })
    return entries


def build_payload(entries):
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "count": len(entries),
        "entries": entries,
    }


def write_data_json(payload, out_path=DATA_OUT):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def build_summary_html(payload):
    generated = html.escape(payload.get("generated") or "")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TC Bench Summary</title>
<style>
  :root { color-scheme: dark; --bg:#070a12; --panel:rgba(255,255,255,.055); --line:rgba(255,255,255,.11); --fg:#e7eef7; --dim:#8a98ad; --accent:#5b8cff; --accent2:#b06bff; --green:#37e6a8; --pink:#ff5cc8; --gold:#ffcc52; }
  * { box-sizing:border-box; }
  body { margin:0; color:var(--fg); font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:radial-gradient(900px 520px at 12% -8%,rgba(91,140,255,.20),transparent 62%),radial-gradient(760px 460px at 100% 0,rgba(176,107,255,.16),transparent 56%),var(--bg); }
  .wrap { max-width:1080px; margin:0 auto; padding:34px 18px 70px; }
  header { display:flex; justify-content:space-between; align-items:flex-end; gap:18px; flex-wrap:wrap; margin-bottom:22px; }
  .badge { display:inline-block; color:var(--accent); border:1px solid var(--line); border-radius:999px; padding:5px 12px; font:700 11px ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing:2px; background:var(--panel); }
  h1 { margin:12px 0 6px; font-size:clamp(34px,6vw,58px); line-height:1; letter-spacing:-1px; background:linear-gradient(120deg,#fff,var(--accent),var(--accent2),var(--pink)); -webkit-background-clip:text; background-clip:text; color:transparent; }
  .sub, .meta { color:var(--dim); }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow:0 20px 50px -24px #000; backdrop-filter:blur(12px); }
  .controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; justify-content:space-between; margin-bottom:14px; }
  .seg { display:inline-flex; gap:4px; padding:4px; border:1px solid var(--line); border-radius:12px; background:rgba(0,0,0,.22); }
  button { border:0; border-radius:9px; padding:8px 14px; color:var(--fg); background:transparent; cursor:pointer; font-weight:700; }
  button.active { background:linear-gradient(120deg,var(--accent),var(--accent2)); color:#fff; }
  input { min-width:220px; flex:1; max-width:360px; color:var(--fg); background:rgba(0,0,0,.26); border:1px solid var(--line); border-radius:10px; padding:9px 13px; }
  table { width:100%; border-collapse:separate; border-spacing:0; font-size:13px; }
  th, td { padding:12px 10px; border-bottom:1px solid rgba(255,255,255,.06); text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
  th { color:var(--dim); text-transform:uppercase; font-size:11px; letter-spacing:1px; }
  th.l, td.l { text-align:left; }
  tbody tr:hover { background:rgba(255,255,255,.045); }
  .rank { color:var(--gold); font-weight:800; }
  .cpu { color:#fff; font-weight:700; }
  .gpu { color:var(--accent); }
  .num { color:var(--green); font-weight:800; }
  .vnum { color:var(--pink); font-weight:800; }
  .muted { color:var(--dim); }
  .foot { color:var(--dim); text-align:center; margin-top:24px; font:12px ui-monospace,SFMono-Regular,Consolas,monospace; }
  @media (max-width:720px) { .wrap { padding:22px 10px 50px; } .panel { padding:12px; } th, td { padding:9px 8px; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="badge">LOCAL SUMMARY</div>
      <h1>TC Bench</h1>
      <div class="sub">score/*.json を埋め込んだ単体HTMLランキング</div>
    </div>
    <div class="meta">Generated: """ + generated + """</div>
  </header>
  <section class="panel">
    <div class="controls">
      <div class="seg" id="sortbar">
        <button data-sort="multi" class="active">Multi</button>
        <button data-sort="single">Single</button>
        <button data-sort="gpu_vcalc">GPU-V</button>
      </div>
      <input id="filter" type="search" placeholder="CPU / GPU 名で絞り込み" autocomplete="off">
      <span class="muted" id="shown"></span>
    </div>
    <div style="overflow:auto">
      <table>
        <thead><tr><th>#</th><th class="l">CPU</th><th class="l">GPU</th><th>Single</th><th>Multi</th><th>GPU-V</th><th>Runs</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </section>
  <div class="foot">This file is standalone. Rebuild with: python tools/build_pages.py</div>
</div>
<script>
const DATA = """ + data + """;
let sortKey = 'multi';
const rowsEl = document.getElementById('rows');
const filterEl = document.getElementById('filter');
const shownEl = document.getElementById('shown');
const fmt = v => Number.isFinite(v) ? Math.round(v).toLocaleString() : '-';
const text = v => v == null || v === '' ? '-' : String(v);
function render(){
  const q = filterEl.value.trim().toLowerCase();
  let rows = DATA.entries.filter(r => !q || text(r.cpu).toLowerCase().includes(q) || text(r.gpu).toLowerCase().includes(q));
  rows.sort((a,b) => (Number(b[sortKey]) || -1) - (Number(a[sortKey]) || -1));
  shownEl.textContent = `${rows.length} / ${DATA.count} entries`;
  rowsEl.innerHTML = rows.map((r,i) => `<tr><td class="rank">${i+1}</td><td class="l cpu">${escapeHtml(text(r.cpu))}</td><td class="l gpu">${escapeHtml(text(r.gpu))}</td><td class="num">${fmt(r.single)}</td><td class="num">${fmt(r.multi)}</td><td class="vnum">${fmt(r.gpu_vcalc)}</td><td>${r.runs || 0}</td></tr>`).join('');
}
function escapeHtml(s){ return s.replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
document.getElementById('sortbar').addEventListener('click', e => {
  const btn = e.target.closest('button[data-sort]');
  if (!btn) return;
  sortKey = btn.dataset.sort;
  document.querySelectorAll('#sortbar button').forEach(b => b.classList.toggle('active', b === btn));
  render();
});
filterEl.addEventListener('input', render);
render();
</script>
</body>
</html>
"""


def write_summary_html(payload, out_path=SUMMARY_OUT):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build_summary_html(payload))


def build(score_dir=SCORE_DIR, data_out=DATA_OUT, summary_out=SUMMARY_OUT):
    payload = build_payload(collect_entries(score_dir))
    write_data_json(payload, data_out)
    write_summary_html(payload, summary_out)
    return payload


def main():
    payload = build()
    print(f"wrote {DATA_OUT} ({payload['count']} entries)")
    print(f"wrote {SUMMARY_OUT} ({payload['count']} entries)")


if __name__ == "__main__":
    main()
