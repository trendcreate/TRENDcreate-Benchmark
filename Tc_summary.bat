@echo off
chcp 65001 >nul
setlocal
REM ============================================================
REM  Tc_summary.bat - TC Bench score summary tool (Windows)
REM    Reads score\*.json and shows the best-score ranking.
REM    Usage: Tc_summary.bat  single / multi / gpu
REM ============================================================

set "SCORE_DIR=%~dp0score"
set "SORT_KEY=%~1"
if "%SORT_KEY%"=="" set "SORT_KEY=multi"

if not exist "%SCORE_DIR%" (
    echo score フォルダが見つかりません: %SCORE_DIR%
    pause
    exit /b 1
)

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
    echo [ERROR] python が見つかりません。
    pause
    exit /b 1
)

set "PYTMP=%TEMP%\tc_summary_%RANDOM%.py"

>  "%PYTMP%" echo import sys, os, json, glob
>> "%PYTMP%" echo SCORE_DIR = sys.argv[1]
>> "%PYTMP%" echo SORT_KEY  = sys.argv[2] if len(sys.argv) ^> 2 else "multi"
>> "%PYTMP%" echo KEYMAP = {"single":"cpu_single","multi":"cpu_multi","gpu":"gpu_vcalc"}
>> "%PYTMP%" echo sort_field = KEYMAP.get(SORT_KEY, "cpu_multi")
>> "%PYTMP%" echo rows = []; skipped = 0
>> "%PYTMP%" echo for path in sorted(glob.glob(os.path.join(SCORE_DIR, "*.json"))):
>> "%PYTMP%" echo     try:
>> "%PYTMP%" echo         if os.path.getsize(path) == 0: skipped += 1; continue
>> "%PYTMP%" echo         with open(path, encoding="utf-8") as f: data = json.load(f)
>> "%PYTMP%" echo     except Exception: skipped += 1; continue
>> "%PYTMP%" echo     si = data.get("system", {}); best = data.get("best", {}); runs = data.get("runs", [])
>> "%PYTMP%" echo     rows.append({"cpu":si.get("cpu_model") or "Unknown","gpu":si.get("gpu_name") or "-","single":best.get("cpu_single"),"multi":best.get("cpu_multi"),"gpu_v":best.get("gpu_vcalc"),"runs":len(runs)})
>> "%PYTMP%" echo if not rows:
>> "%PYTMP%" echo     print("集計対象のスコアがありません。先に Tc_bench を実行してください。"); sys.exit(0)
>> "%PYTMP%" echo bfk = {"cpu_single":"single","cpu_multi":"multi","gpu_vcalc":"gpu_v"}[sort_field]
>> "%PYTMP%" echo rows.sort(key=lambda r: (r[bfk] is None, -(r[bfk] or 0)))
>> "%PYTMP%" echo def fmt(v): return f"{v:,.0f}" if isinstance(v,(int,float)) else "-"
>> "%PYTMP%" echo print("  ==================================================================")
>> "%PYTMP%" echo print("                TC BENCH  スコア集計 / ランキング")
>> "%PYTMP%" echo print("  ==================================================================")
>> "%PYTMP%" echo _skip = f"  /  スキップ: {skipped}" if skipped else ""
>> "%PYTMP%" echo print(f"  並び順: {SORT_KEY}  /  登録数: {len(rows)} 組み合わせ{_skip}\n")
>> "%PYTMP%" echo print(f"  {'#':>2}  {'CPU':<34}{'GPU':<22}{'Single':>8}{'Multi':>9}{'GPU-V':>9}{'Runs':>6}")
>> "%PYTMP%" echo print("  " + "-" * 88)
>> "%PYTMP%" echo for i, r in enumerate(rows, 1):
>> "%PYTMP%" echo     cpu = (r["cpu"][:32] + "..") if len(r["cpu"]) ^> 34 else r["cpu"]
>> "%PYTMP%" echo     gpu = (r["gpu"][:20] + "..") if len(r["gpu"]) ^> 22 else r["gpu"]
>> "%PYTMP%" echo     print(f"  {i:>2}  {cpu:<34}{gpu:<22}{fmt(r['single']):>8}{fmt(r['multi']):>9}{fmt(r['gpu_v']):>9}{r['runs']:>6}")
>> "%PYTMP%" echo print("  " + "-" * 88)
>> "%PYTMP%" echo print("  * 各値は組み合わせごとのベストスコア。並び替え: Tc_summary.bat single / multi / gpu")

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
%PY% "%PYTMP%" "%SCORE_DIR%" "%SORT_KEY%"

del "%PYTMP%" >nul 2>nul
echo.
pause
endlocal
