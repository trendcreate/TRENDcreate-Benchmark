@echo off
chcp 65001 >nul
setlocal
REM ============================================================
REM  Tc_bench.bat - TC Bench CPU/GPU benchmark and diagnostics (Windows)
REM                 Runs on Python3 standard library only.
REM ============================================================

REM ---- score/ directory ------------------------------------
set "SCORE_DIR=%~dp0score"
if not exist "%SCORE_DIR%" mkdir "%SCORE_DIR%" >nul 2>nul

cls
echo.
echo   ============================================================
echo            T C   B E N C H   -  CPU / GPU  v1.0
echo            CPU / GPU Benchmark ^& Diagnostics
echo   ============================================================
echo.

REM ---- Check for Python3 -----------------------------------
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
    echo [ERROR] python が見つかりません。https://www.python.org/ からインストールしてください。
    pause
    exit /b 1
)

REM ---- System info (single PowerShell call) ----------------
echo   -- システム情報 (System Information) --

set "PS1TMP=%TEMP%\tc_sysinfo_%RANDOM%.ps1"
set "INFTMP=%TEMP%\tc_sysinfo_%RANDOM%.txt"

>  "%PS1TMP%" echo $ErrorActionPreference = 'SilentlyContinue'
>> "%PS1TMP%" echo $c = Get-CimInstance Win32_Processor ^| Select-Object -First 1
>> "%PS1TMP%" echo "CPU=" + $c.Name
>> "%PS1TMP%" echo "CORES=" + $c.NumberOfCores
>> "%PS1TMP%" echo "THREADS=" + $c.NumberOfLogicalProcessors
>> "%PS1TMP%" echo "MHZ=" + [int]$c.MaxClockSpeed
>> "%PS1TMP%" echo $l3 = (Get-CimInstance Win32_CacheMemory ^| Where-Object { $_.Level -eq 5 } ^| Measure-Object MaxCacheSize -Sum).Sum
>> "%PS1TMP%" echo if ($l3) { "L3=" + [int]($l3/1024) } else { "L3=0" }
>> "%PS1TMP%" echo $g = $null
>> "%PS1TMP%" echo if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
>> "%PS1TMP%" echo   $g = (nvidia-smi --query-gpu=name,memory.total,clocks.max.sm --format=csv,noheader,nounits) ^| Select-Object -First 1
>> "%PS1TMP%" echo }
>> "%PS1TMP%" echo if ($g) {
>> "%PS1TMP%" echo   $p = $g -split ','
>> "%PS1TMP%" echo   "GPU=" + $p[0].Trim()
>> "%PS1TMP%" echo   "VRAM=" + ($p[1] -replace '[^\d]','')
>> "%PS1TMP%" echo   "SMCLK=" + ($p[2] -replace '[^\d]','')
>> "%PS1TMP%" echo   "VENDOR=NVIDIA"
>> "%PS1TMP%" echo } else {
>> "%PS1TMP%" echo   $vc = Get-CimInstance Win32_VideoController ^| Where-Object { $_.Name -match 'NVIDIA^|AMD^|Radeon^|ATI' } ^| Select-Object -First 1
>> "%PS1TMP%" echo   if ($vc) {
>> "%PS1TMP%" echo     $vram = 0
>> "%PS1TMP%" echo     try { $vram = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*' -Name 'HardwareInformation.qwMemorySize' -ErrorAction SilentlyContinue ^| ForEach-Object { $_.'HardwareInformation.qwMemorySize' } ^| Sort-Object -Descending ^| Select-Object -First 1) } catch {}
>> "%PS1TMP%" echo     if (-not $vram -or $vram -eq 0) { $vram = $vc.AdapterRAM }
>> "%PS1TMP%" echo     "GPU=" + $vc.Name
>> "%PS1TMP%" echo     "VRAM=" + [int]($vram/1MB)
>> "%PS1TMP%" echo     "SMCLK=0"
>> "%PS1TMP%" echo     if ($vc.Name -match 'AMD^|Radeon^|ATI') { "VENDOR=AMD" } else { "VENDOR=NVIDIA" }
>> "%PS1TMP%" echo   } else { "GPU="; "VRAM=0"; "SMCLK=0"; "VENDOR=" }
>> "%PS1TMP%" echo }

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1TMP%" > "%INFTMP%" 2>nul

set "CPU_MODEL="
set "CORES="
set "THREADS="
set "CPU_MHZ=0"
set "L3MB=0"
set "GPU_NAME="
set "GPU_VRAM=0"
set "GPU_SMCLK=0"
set "GPU_VENDOR="
for /f "usebackq tokens=1,* delims==" %%a in ("%INFTMP%") do (
    if "%%a"=="CPU"    set "CPU_MODEL=%%b"
    if "%%a"=="CORES"  set "CORES=%%b"
    if "%%a"=="THREADS" set "THREADS=%%b"
    if "%%a"=="MHZ"    set "CPU_MHZ=%%b"
    if "%%a"=="L3"     set "L3MB=%%b"
    if "%%a"=="GPU"    set "GPU_NAME=%%b"
    if "%%a"=="VRAM"   set "GPU_VRAM=%%b"
    if "%%a"=="SMCLK"  set "GPU_SMCLK=%%b"
    if "%%a"=="VENDOR" set "GPU_VENDOR=%%b"
)
del "%PS1TMP%" >nul 2>nul
del "%INFTMP%" >nul 2>nul

if not defined CPU_MODEL set "CPU_MODEL=Unknown"
if not defined CORES set "CORES=N/A"
if not defined THREADS set "THREADS=%NUMBER_OF_PROCESSORS%"
if "%L3MB%"=="" set "L3MB=0"
if "%L3MB%"=="0" ( set "L3DISP=N/A" ) else ( set "L3DISP=%L3MB% MB" )

set "HAS_GPU=0"
if defined GPU_NAME if not "%GPU_NAME%"=="" set "HAS_GPU=1"
if "%HAS_GPU%"=="0" set "GPU_NAME=N/A"
if "%GPU_VRAM%"=="" set "GPU_VRAM=0"
if "%GPU_SMCLK%"=="" set "GPU_SMCLK=0"
if "%GPU_VENDOR%"=="" set "GPU_VENDOR=GPU"

echo   CPUモデル名        : %CPU_MODEL%
echo   コア数 / スレッド数 : %CORES% cores / %THREADS% threads
if not "%CPU_MHZ%"=="0" echo   動作クロック(最大) : %CPU_MHZ% MHz
echo   L3キャッシュ容量   : %L3DISP%
if "%HAS_GPU%"=="0" goto :gpu_none
echo   GPUモデル名        : %GPU_NAME% [%GPU_VENDOR%]
if "%GPU_SMCLK%"=="0" echo   VRAM総容量         : %GPU_VRAM% MB [クロック不明 - 公称値で算出]
if not "%GPU_SMCLK%"=="0" echo   VRAM総容量         : %GPU_VRAM% MB [最大クロック %GPU_SMCLK% MHz]
goto :gpu_done
:gpu_none
echo   GPU                : NVIDIA/AMD 未検出 - GPUスコアはスキップ [OOM回避モード]
:gpu_done
echo.

REM ---- List saved scores -----------------------------------
if exist "%SCORE_DIR%\*.json" (
    echo   -- 保存済みスコア score/ --
    for %%f in ("%SCORE_DIR%\*.json") do echo   - %%~nxf
    echo.
)

echo   -- ベンチマーク実行中 (全スレッド100%%で負荷をかけます) --
echo.

REM ---- Generate temp Python file ---------------------------
set "PYTMP=%TEMP%\tc_bench_%RANDOM%.py"

>  "%PYTMP%" echo import sys, time, math, os, json, re, platform
>> "%PYTMP%" echo from datetime import datetime, timezone
>> "%PYTMP%" echo from multiprocessing import Pool, cpu_count
>> "%PYTMP%" echo NPROC      = int(sys.argv[1]) if len(sys.argv) ^> 1 else cpu_count()
>> "%PYTMP%" echo HAS_GPU    = sys.argv[2] == "1" if len(sys.argv) ^> 2 else False
>> "%PYTMP%" echo GPU_VRAM   = float(sys.argv[3]) if len(sys.argv) ^> 3 else 0.0
>> "%PYTMP%" echo GPU_SMCLK  = float(sys.argv[4]) if len(sys.argv) ^> 4 else 0.0
>> "%PYTMP%" echo CPU_MODEL  = sys.argv[5] if len(sys.argv) ^> 5 else "Unknown"
>> "%PYTMP%" echo GPU_NAME   = sys.argv[6] if len(sys.argv) ^> 6 else "N/A"
>> "%PYTMP%" echo SCORE_DIR  = sys.argv[7] if len(sys.argv) ^> 7 else "score"
>> "%PYTMP%" echo ARCH       = sys.argv[8] if len(sys.argv) ^> 8 else ""
>> "%PYTMP%" echo CORES      = sys.argv[9] if len(sys.argv) ^> 9 else ""
>> "%PYTMP%" echo L3_CACHE   = sys.argv[10] if len(sys.argv) ^> 10 else ""
>> "%PYTMP%" echo GPU_VENDOR = sys.argv[11] if len(sys.argv) ^> 11 else ""
>> "%PYTMP%" echo CPU_MHZ    = int(sys.argv[12]) if len(sys.argv) ^> 12 and sys.argv[12].isdigit() else 0
>> "%PYTMP%" echo WORK_LIMIT = 600000
>> "%PYTMP%" echo def heavy_work(limit):
>> "%PYTMP%" echo     count = 0; acc = 0.0; n = 2
>> "%PYTMP%" echo     while n ^< limit:
>> "%PYTMP%" echo         is_prime = True; r = int(math.isqrt(n)); d = 2
>> "%PYTMP%" echo         while d ^<= r:
>> "%PYTMP%" echo             if n %% d == 0:
>> "%PYTMP%" echo                 is_prime = False; break
>> "%PYTMP%" echo             d += 1
>> "%PYTMP%" echo         if is_prime:
>> "%PYTMP%" echo             count += 1; acc += math.sqrt(n) * math.sin(n) + math.log(n + 1)
>> "%PYTMP%" echo         n += 1
>> "%PYTMP%" echo     return (count, acc)
>> "%PYTMP%" echo def run_pool(workers, tasks):
>> "%PYTMP%" echo     start = time.perf_counter()
>> "%PYTMP%" echo     with Pool(processes=workers) as pool:
>> "%PYTMP%" echo         pool.map(heavy_work, [WORK_LIMIT] * tasks)
>> "%PYTMP%" echo     return time.perf_counter() - start
>> "%PYTMP%" echo def bar(score, max_score, width=40):
>> "%PYTMP%" echo     if max_score ^<= 0: max_score = 1
>> "%PYTMP%" echo     filled = int(round((score / max_score) * width))
>> "%PYTMP%" echo     filled = max(0, min(width, filled))
>> "%PYTMP%" echo     return "[" + "#" * filled + "." * (width - filled) + "]"
>> "%PYTMP%" echo if __name__ == "__main__":
>> "%PYTMP%" echo     print("  [1/2] シングルスレッド性能テスト 実行中...", flush=True)
>> "%PYTMP%" echo     single_time = run_pool(1, 1)
>> "%PYTMP%" echo     print(f"        完了: {single_time:.2f} 秒\n", flush=True)
>> "%PYTMP%" echo     print(f"  [2/2] マルチスレッド性能テスト ({NPROC} スレッド) 実行中...", flush=True)
>> "%PYTMP%" echo     multi_time = run_pool(NPROC, NPROC)
>> "%PYTMP%" echo     print(f"        完了: {multi_time:.2f} 秒\n", flush=True)
>> "%PYTMP%" echo     SCORE_FACTOR = 10000.0
>> "%PYTMP%" echo     single_score = SCORE_FACTOR / single_time
>> "%PYTMP%" echo     multi_score  = (SCORE_FACTOR * NPROC) / multi_time
>> "%PYTMP%" echo     ratio        = single_time / multi_time if multi_time ^> 0 else 0.0
>> "%PYTMP%" echo     gpu_score = 0.0; gpu_estimated = False
>> "%PYTMP%" echo     if HAS_GPU and GPU_VRAM ^> 0:
>> "%PYTMP%" echo         vram_gb = GPU_VRAM / 1024.0
>> "%PYTMP%" echo         clk = GPU_SMCLK if GPU_SMCLK ^> 0 else 1500.0
>> "%PYTMP%" echo         if GPU_SMCLK ^<= 0: gpu_estimated = True
>> "%PYTMP%" echo         gpu_score = (clk * (vram_gb ** 1.5)) / 10.0
>> "%PYTMP%" echo     print("  ==================================================================")
>> "%PYTMP%" echo     print("                  >> BENCHMARK  RESULT  SCORE <<")
>> "%PYTMP%" echo     print("  ==================================================================")
>> "%PYTMP%" echo     scores = [single_score, multi_score] + ([gpu_score] if gpu_score ^> 0 else [])
>> "%PYTMP%" echo     max_score = max(scores) if scores else 1.0
>> "%PYTMP%" echo     print(f"  CPU Single {bar(single_score, max_score)} {single_score:7.0f} pts (優しさの証)")
>> "%PYTMP%" echo     print(f"  CPU Multi  {bar(multi_score, max_score)} {multi_score:7.0f} pts (全スレッド全力回転)")
>> "%PYTMP%" echo     if gpu_score ^> 0:
>> "%PYTMP%" echo         _note = "(VRAM暴力の真価)" + (" ※クロック公称値" if gpu_estimated else "")
>> "%PYTMP%" echo         _vd = f"[{GPU_VENDOR}]" if GPU_VENDOR else ""
>> "%PYTMP%" echo         print(f"  GPU V-Calc {bar(gpu_score, max_score)} {gpu_score:7.0f} pts {_note} {_vd}")
>> "%PYTMP%" echo     else:
>> "%PYTMP%" echo         print("  GPU V-Calc [........................................]   SKIPPED (NVIDIA/AMD未検出 / OOM回避)")
>> "%PYTMP%" echo     print("  ------------------------------------------------------------------")
>> "%PYTMP%" echo     print(f"  マルチコア倍率 : {ratio:.2f}x  (Single {single_time:.2f}s / Multi {multi_time:.2f}s)")
>> "%PYTMP%" echo     def slug(s):
>> "%PYTMP%" echo         s = re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "").strip())
>> "%PYTMP%" echo         return s.strip("_") or "unknown"
>> "%PYTMP%" echo     combo = f"{slug(CPU_MODEL)}__{slug(GPU_NAME)}"
>> "%PYTMP%" echo     path  = os.path.join(SCORE_DIR, combo + ".json")
>> "%PYTMP%" echo     record = {"schema":"tc_bench/score/v1","timestamp":datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),"os":platform.platform(),"system":{"cpu_model":CPU_MODEL,"architecture":ARCH,"cores_per_socket":CORES,"logical_processors":NPROC,"cpu_mhz":(CPU_MHZ if CPU_MHZ^>0 else None),"l3_cache":L3_CACHE,"gpu_name":GPU_NAME if HAS_GPU else None,"gpu_vendor":GPU_VENDOR if HAS_GPU else None,"gpu_vram_mb":GPU_VRAM if HAS_GPU else None,"gpu_sm_clock_mhz":(GPU_SMCLK if (HAS_GPU and GPU_SMCLK^>0) else None)},"scores":{"cpu_single":round(single_score,1),"cpu_multi":round(multi_score,1),"gpu_vcalc":round(gpu_score,1) if gpu_score^>0 else None,"multi_ratio":round(ratio,2),"single_time_s":round(single_time,3),"multi_time_s":round(multi_time,3)}}
>> "%PYTMP%" echo     data = {"combo":combo,"system":record["system"],"best":{},"runs":[]}
>> "%PYTMP%" echo     if os.path.exists(path):
>> "%PYTMP%" echo         try:
>> "%PYTMP%" echo             with open(path, encoding="utf-8") as f: data = json.load(f)
>> "%PYTMP%" echo             data.setdefault("runs", []); data.setdefault("best", {})
>> "%PYTMP%" echo         except Exception: pass
>> "%PYTMP%" echo     prev_best = data.get("best", {})
>> "%PYTMP%" echo     def cmp_line(label, key, cur):
>> "%PYTMP%" echo         if cur is None: return
>> "%PYTMP%" echo         pb = prev_best.get(key)
>> "%PYTMP%" echo         if pb is None: tag = "NEW"
>> "%PYTMP%" echo         elif cur ^>= pb: tag = f">> ベスト更新! (旧 {pb:.0f})"
>> "%PYTMP%" echo         else: tag = f"過去ベスト {pb:.0f}"
>> "%PYTMP%" echo         print(f"  {label:<12}: {cur:7.0f} pts  {tag}")
>> "%PYTMP%" echo     print(f"  -- 過去スコアとの比較 ({combo}) --")
>> "%PYTMP%" echo     cmp_line("CPU Single", "cpu_single", single_score)
>> "%PYTMP%" echo     cmp_line("CPU Multi",  "cpu_multi",  multi_score)
>> "%PYTMP%" echo     if gpu_score ^> 0: cmp_line("GPU V-Calc", "gpu_vcalc", gpu_score)
>> "%PYTMP%" echo     for k, v in record["scores"].items():
>> "%PYTMP%" echo         if v is None or k in ("single_time_s","multi_time_s"): continue
>> "%PYTMP%" echo         if data["best"].get(k) is None or v ^> data["best"][k]: data["best"][k] = v
>> "%PYTMP%" echo     data["system"] = record["system"]; data["runs"].append(record)
>> "%PYTMP%" echo     tmp = path + ".tmp"
>> "%PYTMP%" echo     try:
>> "%PYTMP%" echo         with open(tmp, "w", encoding="utf-8") as f:
>> "%PYTMP%" echo             json.dump(data, f, ensure_ascii=False, indent=2); f.flush(); os.fsync(f.fileno())
>> "%PYTMP%" echo         os.replace(tmp, path)
>> "%PYTMP%" echo         print(f"  スコアを保存しました: {path}")
>> "%PYTMP%" echo         print("  (このJSONファイルを共有すれば結果を比較できます)")
>> "%PYTMP%" echo     except Exception as e:
>> "%PYTMP%" echo         try:
>> "%PYTMP%" echo             if os.path.exists(tmp): os.remove(tmp)
>> "%PYTMP%" echo         except Exception: pass
>> "%PYTMP%" echo         print(f"  スコア保存に失敗: {e}")

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
%PY% "%PYTMP%" %THREADS% %HAS_GPU% %GPU_VRAM% %GPU_SMCLK% "%CPU_MODEL%" "%GPU_NAME%" "%SCORE_DIR%" "%PROCESSOR_ARCHITECTURE%" "%CORES%" "%L3DISP%" "%GPU_VENDOR%" "%CPU_MHZ%"

del "%PYTMP%" >nul 2>nul

echo.
echo   ベンチマーク完了。お疲れ様でした！
pause
endlocal
