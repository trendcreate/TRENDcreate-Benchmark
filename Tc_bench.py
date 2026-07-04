#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TC Bench CPU/GPU benchmark and score summary tool."""

from __future__ import print_function

import argparse
import datetime
import glob
import json
import math
import multiprocessing as mp
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCORE_DIR = os.path.join(ROOT, "score")
SUMMARY_HTML = os.path.join(ROOT, "summary.html")
DEFAULT_WORK_LIMIT = int(os.environ.get("TC_BENCH_WORK_LIMIT", "600000"))
SCORE_FACTOR = 10000.0
NOMINAL_GPU_CLOCK_MHZ = 1500.0
SORT_KEYS = ("single", "multi", "gpu")
# 画像生成(Diffusion)テストのゲート条件: VRAM総量 >= 4GB かつ 空き >= 2GB
DIFFUSION_MIN_VRAM_MB = 4096
DIFFUSION_MIN_FREE_MB = 2048
# プラグイン (後からダウンロードして追加できる拡張ベンチ)
PLUGIN_DIR = os.path.join(ROOT, "plugins")
PLUGIN_BASE_URL = "https://raw.githubusercontent.com/trendcreate/TRENDcreate-Benchmark/main/plugins/"


def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def enable_windows_ansi():
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


USE_COLOR = False


def init_color():
    global USE_COLOR
    USE_COLOR = bool(sys.stdout.isatty() and enable_windows_ansi())


def color(code):
    return "\033[{}m".format(code) if USE_COLOR else ""


C_RESET = lambda: color("0")
C_BOLD = lambda: color("1")
C_RED = lambda: color("31")
C_GREEN = lambda: color("32")
C_YELLOW = lambda: color("33")
C_CYAN = lambda: color("36")
C_MAGENTA = lambda: color("35")


def run_cmd(args, timeout=8):
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw = proc.communicate(timeout=timeout)[0]
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return ""
    for enc in ("utf-8", "cp932", sys.getdefaultencoding()):
        try:
            return raw.decode(enc, "replace")
        except Exception:
            pass
    return raw.decode("utf-8", "replace")


def run_powershell(script):
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return ""
    args = [exe, "-NoProfile"]
    if os.path.basename(exe).lower() == "powershell.exe":
        args.extend(["-ExecutionPolicy", "Bypass"])
    args.extend(["-Command", script])
    return run_cmd(args, timeout=15)


def first_int(value):
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def first_float(value):
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return ""


def merge_info(base, updates):
    for key, value in (updates or {}).items():
        if value is not None and value != "":
            base[key] = value


def vendor_from_name(name):
    name = name or ""
    if re.search(r"NVIDIA|GeForce|RTX|GTX", name, re.I):
        return "NVIDIA"
    if re.search(r"AMD|Radeon|ATI", name, re.I):
        return "AMD"
    if re.search(r"Intel", name, re.I):
        return "Intel"
    if re.search(r"Apple", name, re.I):
        return "Apple"
    return ""


def parse_key_values(text):
    values = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def default_system_info():
    return {
        "cpu_model": platform.processor() or "Unknown",
        "architecture": platform.machine() or platform.platform(),
        "cores_per_socket": None,
        "logical_processors": os.cpu_count() or 1,
        "cpu_mhz": None,
        "l3_cache": "N/A",
        "gpu_name": None,
        "gpu_vendor": None,
        "gpu_vram_mb": None,
        "gpu_vram_free_mb": None,
        "gpu_sm_clock_mhz": None,
    }


def query_nvidia_smi():
    if not shutil.which("nvidia-smi"):
        return {}
    out = run_cmd([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,clocks.max.sm",
        "--format=csv,noheader,nounits",
    ])
    line = next((x.strip() for x in out.splitlines() if x.strip()), "")
    if not line:
        return {}
    parts = [x.strip() for x in line.split(",")]
    return {
        "gpu_name": parts[0] if len(parts) > 0 else "NVIDIA GPU",
        "gpu_vendor": "NVIDIA",
        "gpu_vram_mb": first_float(parts[1]) if len(parts) > 1 else None,
        "gpu_vram_free_mb": first_float(parts[2]) if len(parts) > 2 else None,
        "gpu_sm_clock_mhz": first_float(parts[3]) if len(parts) > 3 else None,
    }


def query_windows_info():
    script = r'''
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$c = Get-CimInstance Win32_Processor | Select-Object -First 1
if ($c) {
  "CPU=" + $c.Name
  "CORES=" + $c.NumberOfCores
  "THREADS=" + $c.NumberOfLogicalProcessors
  "MHZ=" + [int]$c.MaxClockSpeed
}
$l3 = (Get-CimInstance Win32_CacheMemory | Where-Object { $_.Level -eq 5 } | Measure-Object MaxCacheSize -Sum).Sum
if ($l3) { "L3=" + [int]($l3/1024) } else { "L3=0" }
$vc = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA|AMD|Radeon|ATI' } | Select-Object -First 1
if ($vc) {
  $vram = 0
  try {
    $vram = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*' -Name 'HardwareInformation.qwMemorySize' -ErrorAction SilentlyContinue | ForEach-Object { $_.'HardwareInformation.qwMemorySize' } | Sort-Object -Descending | Select-Object -First 1)
  } catch {}
  if (-not $vram -or $vram -eq 0) { $vram = $vc.AdapterRAM }
  "GPU=" + $vc.Name
  "VRAM=" + [int]($vram/1MB)
  if ($vc.Name -match 'AMD|Radeon|ATI') { "VENDOR=AMD" } else { "VENDOR=NVIDIA" }
}
'''
    values = parse_key_values(run_powershell(script))
    l3_mb = first_int(values.get("L3"))
    return {
        "cpu_model": values.get("CPU"),
        "architecture": os.environ.get("PROCESSOR_ARCHITECTURE") or platform.machine(),
        "cores_per_socket": values.get("CORES"),
        "logical_processors": first_int(values.get("THREADS")),
        "cpu_mhz": first_float(values.get("MHZ")),
        "l3_cache": "{} MB".format(l3_mb) if l3_mb else "N/A",
        "gpu_name": values.get("GPU"),
        "gpu_vendor": values.get("VENDOR"),
        "gpu_vram_mb": first_float(values.get("VRAM")),
    }


def parse_lscpu():
    raw = run_cmd(["lscpu"])
    data = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip().casefold()] = value.strip()
    return data


def get_lscpu(data, *keys):
    for key in keys:
        value = data.get(key.casefold())
        if value:
            return value
    return None


def query_linux_cpu_info():
    data = parse_lscpu()
    cpu_mhz = first_float(get_lscpu(data, "CPU max MHz", "CPU MHz"))
    return {
        "cpu_model": get_lscpu(data, "Model name", "モデル名") or platform.processor() or "Unknown",
        "architecture": get_lscpu(data, "Architecture", "アーキテクチャ") or platform.machine(),
        "cores_per_socket": get_lscpu(data, "Core(s) per socket", "ソケットあたりのコア数"),
        "logical_processors": os.cpu_count() or 1,
        "cpu_mhz": cpu_mhz,
        "l3_cache": get_lscpu(data, "L3 cache", "L3 キャッシュ") or "N/A",
    }


def query_rocm_smi():
    if not shutil.which("rocm-smi"):
        return {}
    name_out = run_cmd(["rocm-smi", "--showproductname"])
    mem_out = run_cmd(["rocm-smi", "--showmeminfo", "vram"])
    clk_out = run_cmd(["rocm-smi", "--showmaxclocks"])
    name = ""
    for line in name_out.splitlines():
        if re.search(r"Card series|Card model|Product Name", line, re.I):
            name = line.split(":", 1)[-1].strip()
            break
    mem_match = re.search(r"Total[^\n:]*:?\s*(\d+)", mem_out, re.I)
    vram_mb = int(mem_match.group(1)) / 1048576.0 if mem_match else None
    clk = first_float(next((line for line in clk_out.splitlines() if re.search(r"sclk", line, re.I)), ""))
    if not name and not vram_mb:
        return {}
    return {
        "gpu_name": name or "AMD GPU",
        "gpu_vendor": "AMD",
        "gpu_vram_mb": vram_mb,
        "gpu_sm_clock_mhz": clk,
    }


def query_lspci_name(pattern):
    if not shutil.which("lspci"):
        return ""
    for line in run_cmd(["lspci"]).splitlines():
        if re.search(r"VGA|3D|Display", line, re.I) and re.search(pattern, line, re.I):
            return line.split(": ", 1)[-1].strip()
    return ""


def query_glxinfo_vram():
    if not shutil.which("glxinfo"):
        return None
    for line in run_cmd(["glxinfo"]).splitlines():
        if re.search(r"Video memory|Dedicated video memory", line, re.I):
            return first_float(line)
    return None


def query_lspci_bar_vram():
    if not shutil.which("lspci"):
        return None
    text = run_cmd(["lspci", "-v"])
    in_display = False
    for line in text.splitlines():
        if re.search(r"VGA|3D|Display", line, re.I):
            in_display = True
        elif not line.strip():
            in_display = False
        if in_display and "prefetchable" in line.lower():
            match = re.search(r"size=(\d+)\s*([MG])", line, re.I)
            if match:
                value = int(match.group(1))
                return value * 1024 if match.group(2).upper() == "G" else value
    return None


def query_amd_sysfs():
    for dev in glob.glob("/sys/class/drm/card[0-9]*/device"):
        if read_text(os.path.join(dev, "vendor")).lower() != "0x1002":
            continue
        vram_bytes = first_int(read_text(os.path.join(dev, "mem_info_vram_total")))
        used_bytes = first_int(read_text(os.path.join(dev, "mem_info_vram_used")))
        clk_values = [int(x) for x in re.findall(r"(\d+)\s*mhz", read_text(os.path.join(dev, "pp_dpm_sclk")), re.I)]
        name = query_lspci_name(r"AMD|ATI|Radeon") or "AMD GPU"
        free_mb = ((vram_bytes - used_bytes) / 1048576.0) if (vram_bytes and used_bytes is not None) else None
        return {
            "gpu_name": name,
            "gpu_vendor": "AMD",
            "gpu_vram_mb": (vram_bytes / 1048576.0) if vram_bytes else None,
            "gpu_vram_free_mb": free_mb,
            "gpu_sm_clock_mhz": max(clk_values) if clk_values else None,
        }
    return {}


def query_linux_amd_gpu():
    info = query_rocm_smi() or query_amd_sysfs()
    if not info:
        name = query_lspci_name(r"AMD|ATI|Radeon")
        if name:
            info = {"gpu_name": name, "gpu_vendor": "AMD"}
    if info:
        if not info.get("gpu_vram_mb"):
            info["gpu_vram_mb"] = query_glxinfo_vram() or query_lspci_bar_vram()
        if not info.get("gpu_vendor"):
            info["gpu_vendor"] = vendor_from_name(info.get("gpu_name"))
    return info


def sysctl_value(name):
    return run_cmd(["sysctl", "-n", name]).strip()


def query_macos_info():
    cpu_hz = first_float(sysctl_value("hw.cpufrequency_max") or sysctl_value("hw.cpufrequency"))
    l3_bytes = first_float(sysctl_value("hw.l3cachesize"))
    info = {
        "cpu_model": sysctl_value("machdep.cpu.brand_string") or platform.processor() or "Unknown",
        "architecture": platform.machine(),
        "cores_per_socket": sysctl_value("hw.physicalcpu") or None,
        "logical_processors": first_int(sysctl_value("hw.logicalcpu")) or os.cpu_count() or 1,
        "cpu_mhz": (cpu_hz / 1000000.0) if cpu_hz else None,
        "l3_cache": "{} MB".format(int(l3_bytes / 1048576)) if l3_bytes else "N/A",
    }
    sp = run_cmd(["system_profiler", "SPDisplaysDataType"], timeout=20)
    name = ""
    vram = None
    for line in sp.splitlines():
        line = line.strip()
        if line.startswith("Chipset Model:") and not name:
            name = line.split(":", 1)[1].strip()
        elif line.startswith("VRAM") and vram is None:
            vram = first_float(line)
            if vram and "GB" in line.upper():
                vram *= 1024
    if name and vendor_from_name(name) in ("NVIDIA", "AMD"):
        info.update({"gpu_name": name, "gpu_vendor": vendor_from_name(name), "gpu_vram_mb": vram})
    return info


def collect_system_info():
    info = default_system_info()
    if sys.platform.startswith("win"):
        merge_info(info, query_windows_info())
    elif sys.platform == "darwin":
        merge_info(info, query_macos_info())
    else:
        merge_info(info, query_linux_cpu_info())

    nvidia = query_nvidia_smi()
    if nvidia:
        merge_info(info, nvidia)
    elif not sys.platform.startswith("win") and sys.platform != "darwin":
        merge_info(info, query_linux_amd_gpu())

    if info.get("gpu_name") and not info.get("gpu_vendor"):
        info["gpu_vendor"] = vendor_from_name(info.get("gpu_name"))
    info["logical_processors"] = int(info.get("logical_processors") or os.cpu_count() or 1)
    info["cpu_model"] = info.get("cpu_model") or "Unknown"
    return info


def heavy_work(limit):
    count = 0
    acc = 0.0
    n = 2
    while n < limit:
        is_prime = True
        root = int(math.isqrt(n))
        d = 2
        while d <= root:
            if n % d == 0:
                is_prime = False
                break
            d += 1
        if is_prime:
            count += 1
            acc += math.sqrt(n) * math.sin(n) + math.log(n + 1)
        n += 1
    return count, acc


def run_pool(workers, tasks, work_limit):
    start = time.perf_counter()
    with mp.Pool(processes=workers) as pool:
        pool.map(heavy_work, [work_limit] * tasks)
    return time.perf_counter() - start


def bar(score, max_score, width=40):
    if max_score <= 0:
        max_score = 1
    filled = int(round((score / max_score) * width))
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def slug(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return value.strip("_") or "unknown"


def print_banner():
    print()
    print("  ============================================================")
    print("           T C   B E N C H   -  CPU / GPU  v1.0")
    print("           CPU / GPU Benchmark & Diagnostics")
    print("  ============================================================")
    print()


def print_system_info(info):
    print("  -- システム情報 (System Information) --")
    print("  CPUモデル名        : {}".format(info.get("cpu_model") or "Unknown"))
    print("  アーキテクチャ     : {}".format(info.get("architecture") or "N/A"))
    print("  コア数 / スレッド数 : {} cores / {} threads".format(info.get("cores_per_socket") or "N/A", info.get("logical_processors") or "N/A"))
    if info.get("cpu_mhz"):
        print("  動作クロック(最大) : {} MHz".format(int(float(info["cpu_mhz"]))))
    print("  L3キャッシュ容量   : {}".format(info.get("l3_cache") or "N/A"))

    if info.get("gpu_name"):
        vendor = " [{}]".format(info.get("gpu_vendor")) if info.get("gpu_vendor") else ""
        print("  GPUモデル名        : {}{}".format(info.get("gpu_name"), vendor))
        vram = info.get("gpu_vram_mb") or 0
        clock = info.get("gpu_sm_clock_mhz") or 0
        if clock:
            print("  VRAM総容量         : {:.0f} MB [最大クロック {:.0f} MHz]".format(vram, clock))
        elif vram:
            print("  VRAM総容量         : {:.0f} MB [クロック不明 - 公称値で算出]".format(vram))
        else:
            print("  VRAM総容量         : N/A [GPUスコアはスキップ]")
        free = info.get("gpu_vram_free_mb")
        if free is not None:
            print("  VRAM空き容量       : {:.0f} MB".format(free))
        ready, _total, _free = diffusion_gate(info)
        if ready is True:
            print("  画像生成テスト     : 対象 [VRAM {}GB以上 & 空き {}GB以上] ※実測は今後対応".format(
                DIFFUSION_MIN_VRAM_MB // 1024, DIFFUSION_MIN_FREE_MB // 1024))
        elif ready is False:
            print("  画像生成テスト     : 対象外 [VRAM {}GB以上 & 空き {}GB以上が必要]".format(
                DIFFUSION_MIN_VRAM_MB // 1024, DIFFUSION_MIN_FREE_MB // 1024))
        else:
            print("  画像生成テスト     : 判定不可 [空きVRAM未取得]")
    else:
        print("  GPU                : NVIDIA/AMD 未検出 - GPUスコアはスキップ [OOM回避モード]")
    print()


def print_saved_scores(score_dir):
    files = sorted(glob.glob(os.path.join(score_dir, "*.json")))
    if not files:
        return
    print("  -- 保存済みスコア score/ --")
    for path in files:
        print("  - {}".format(os.path.basename(path)))
    print()


def score_gpu(info):
    vendor = info.get("gpu_vendor") or vendor_from_name(info.get("gpu_name"))
    vram = float(info.get("gpu_vram_mb") or 0)
    clock = float(info.get("gpu_sm_clock_mhz") or 0)
    if vendor not in ("NVIDIA", "AMD") or vram <= 0:
        return 0.0, False
    estimated = clock <= 0
    if estimated:
        clock = NOMINAL_GPU_CLOCK_MHZ
    return (clock * ((vram / 1024.0) ** 1.5)) / 10.0, estimated


def diffusion_gate(info):
    """画像生成(Diffusion)テストのゲート判定。

    戻り値 (ready, total_mb, free_mb):
      ready = True  … VRAM総量>=4GB かつ 空き>=2GB（テスト対象）
      ready = False … 条件を満たさない（対象外）
      ready = None  … 空きVRAMが取得できず判定不可
    """
    vendor = info.get("gpu_vendor")
    total = info.get("gpu_vram_mb")
    free = info.get("gpu_vram_free_mb")
    if vendor not in ("NVIDIA", "AMD") or not total:
        return False, total, free
    if total < DIFFUSION_MIN_VRAM_MB:
        return False, total, free
    if free is None:
        return None, total, free
    return (free >= DIFFUSION_MIN_FREE_MB), total, free


# ---------------------------------------------------------------------------
# プラグイン機構 (後からダウンロードして追加できる拡張ベンチ)
#   plugins/*.py が満たすべきインターフェース:
#     NAME        : str           プラグイン名
#     DESCRIPTION : str           説明 (任意)
#     available() -> (bool, str)  依存が揃っているか + メッセージ (任意)
#     should_run(info) -> bool    実行条件 (任意, 既定 True)
#     run(info) -> dict           {score_key: 数値, ...} を返す
# ---------------------------------------------------------------------------
def _load_plugin_module(path):
    import importlib.util
    mod_name = "tcplugin_" + re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(os.path.basename(path))[0])
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_plugins():
    plugins = []
    if not os.path.isdir(PLUGIN_DIR):
        return plugins
    for path in sorted(glob.glob(os.path.join(PLUGIN_DIR, "*.py"))):
        if os.path.basename(path).startswith("_"):
            continue
        try:
            module = _load_plugin_module(path)
        except Exception as exc:
            print("  [plugin] 読み込み失敗 {}: {}".format(os.path.basename(path), exc))
            continue
        if hasattr(module, "run") and hasattr(module, "NAME"):
            plugins.append(module)
    return plugins


def run_plugins(info):
    """インストール済みプラグインを実行し {score_key: value} を返す。"""
    results = {}
    plugins = discover_plugins()
    if not plugins:
        return results
    print("  -- 追加ベンチ (プラグイン) --")
    for module in plugins:
        name = getattr(module, "NAME", "?")
        try:
            ok, message = module.available() if hasattr(module, "available") else (True, "")
        except Exception as exc:
            ok, message = False, str(exc)
        if not ok:
            print("  [{}] スキップ: {}".format(name, message or "利用不可"))
            continue
        try:
            if hasattr(module, "should_run") and not module.should_run(info):
                print("  [{}] スキップ: 実行条件を満たしません".format(name))
                continue
        except Exception as exc:
            print("  [{}] スキップ: {}".format(name, exc))
            continue
        try:
            out = module.run(info) or {}
        except Exception as exc:
            print("  [{}] 実行失敗: {}".format(name, exc))
            continue
        if isinstance(out, dict):
            clean = {k: float(v) for k, v in out.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            results.update(clean)
            detail = ", ".join("{}={:.1f}".format(k, v) for k, v in clean.items()) or "結果なし"
            print("  [{}] 完了: {}".format(name, detail))
    print()
    return results


def _fetch_url(url, timeout=30):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "TC-Bench"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_plugin_registry():
    local = os.path.join(PLUGIN_DIR, "registry.json")
    if os.path.exists(local):
        try:
            with open(local, encoding="utf-8") as f:
                return json.load(f).get("plugins", [])
        except Exception:
            pass
    try:
        data = json.loads(_fetch_url(PLUGIN_BASE_URL + "registry.json").decode("utf-8"))
        return data.get("plugins", [])
    except Exception as exc:
        print("  レジストリ取得に失敗しました: {}".format(exc))
        return []


def run_plugin_command(args):
    action = args.action or "list"
    registry = load_plugin_registry()

    if action == "list":
        if not registry:
            print("利用可能なプラグインがありません。")
            return 0
        print("  利用可能なプラグイン:")
        for entry in registry:
            fname = entry.get("file") or (entry.get("name", "") + ".py")
            installed = os.path.exists(os.path.join(PLUGIN_DIR, fname))
            print("  - {:<12} {} {}".format(entry.get("name"), "[導入済]" if installed else "[未導入]", entry.get("description", "")))
            if entry.get("requires"):
                print("      依存: {}".format(entry["requires"]))
        print("\n  導入: python Tc_bench.py plugin install <名前>")
        return 0

    name = args.name
    if not name:
        print("プラグイン名を指定してください。例: python Tc_bench.py plugin {} diffusion".format(action))
        return 1
    entry = next((p for p in registry if p.get("name") == name), None)
    fname = (entry.get("file") if entry else None) or (name + ".py")
    dest = os.path.join(PLUGIN_DIR, fname)

    if action == "remove":
        if os.path.exists(dest):
            os.remove(dest)
            print("削除しました: {}".format(dest))
        else:
            print("プラグイン '{}' は未導入です。".format(name))
        return 0

    if action == "install":
        if not entry:
            print("プラグイン '{}' が見つかりません。`plugin list` で確認してください。".format(name))
            return 1
        os.makedirs(PLUGIN_DIR, exist_ok=True)
        try:
            data = _fetch_url(PLUGIN_BASE_URL + fname)
        except Exception as exc:
            print("ダウンロードに失敗しました: {}".format(exc))
            return 1
        with open(dest, "wb") as f:
            f.write(data)
        print("インストールしました: {}".format(dest))
        if entry.get("requires"):
            print("※ このプラグインは追加の依存が必要です: {}".format(entry["requires"]))
            print("   （依存が無い場合、ベンチ実行時に自動でスキップされます）")
        return 0

    print("使い方: python Tc_bench.py plugin [list | install <名前> | remove <名前>]")
    return 0


def atomic_write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def save_score(score_dir, info, scores, single_time, multi_time, ratio, plugin_scores=None):
    combo = "{}__{}".format(slug(info.get("cpu_model")), slug(info.get("gpu_name") or "N_A"))
    path = os.path.join(score_dir, combo + ".json")
    record = {
        "schema": "tc_bench/score/v1",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "os": platform.platform(),
        "system": {
            "cpu_model": info.get("cpu_model"),
            "architecture": info.get("architecture"),
            "cores_per_socket": info.get("cores_per_socket"),
            "logical_processors": info.get("logical_processors"),
            "cpu_mhz": info.get("cpu_mhz"),
            "l3_cache": info.get("l3_cache"),
            "gpu_name": info.get("gpu_name"),
            "gpu_vendor": info.get("gpu_vendor"),
            "gpu_vram_mb": info.get("gpu_vram_mb"),
            "gpu_vram_free_mb": info.get("gpu_vram_free_mb"),
            "gpu_sm_clock_mhz": info.get("gpu_sm_clock_mhz"),
            "diffusion_ready": diffusion_gate(info)[0],
        },
        "scores": {
            "cpu_single": round(scores["single"], 1),
            "cpu_multi": round(scores["multi"], 1),
            "gpu_vcalc": round(scores["gpu"], 1) if scores["gpu"] > 0 else None,
            "multi_ratio": round(ratio, 2),
            "single_time_s": round(single_time, 3),
            "multi_time_s": round(multi_time, 3),
        },
    }
    for key, value in (plugin_scores or {}).items():
        record["scores"][key] = round(value, 1)
    data = {"combo": combo, "system": record["system"], "best": {}, "runs": []}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("runs", [])
            data.setdefault("best", {})
        except Exception:
            pass

    prev_best = data.get("best", {})
    print("  -- 過去スコアとの比較 ({}) --".format(combo))

    def cmp_line(label, key, current):
        if current is None:
            return
        previous = prev_best.get(key)
        if previous is None:
            tag = "NEW"
        elif current >= previous:
            tag = ">> ベスト更新! (旧 {:.0f})".format(previous)
        else:
            tag = "過去ベスト {:.0f}".format(previous)
        print("  {:<12}: {:7.0f} pts  {}".format(label, current, tag))

    cmp_line("CPU Single", "cpu_single", scores["single"])
    cmp_line("CPU Multi", "cpu_multi", scores["multi"])
    if scores["gpu"] > 0:
        cmp_line("GPU V-Calc", "gpu_vcalc", scores["gpu"])

    for key, value in record["scores"].items():
        if value is None or key in ("single_time_s", "multi_time_s"):
            continue
        if data["best"].get(key) is None or value > data["best"][key]:
            data["best"][key] = value
    data["combo"] = combo
    data["system"] = record["system"]
    data["runs"].append(record)
    atomic_write_json(path, data)
    return path


def generate_summary_html():
    script = os.path.join(ROOT, "tools", "build_pages.py")
    if not os.path.exists(script):
        return None, "tools/build_pages.py が見つからないため summary.html 生成をスキップしました。"
    proc = subprocess.Popen(
        [sys.executable, script],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate()
    if proc.returncode != 0:
        message = err.decode("utf-8", "replace").strip() or out.decode("utf-8", "replace").strip()
        return None, "summary.html 生成に失敗しました: {}".format(message or "unknown error")
    if not os.path.exists(SUMMARY_HTML):
        return None, "summary.html 生成に失敗しました: ファイルが見つかりません。"
    return SUMMARY_HTML, None


def open_html_file(path):
    abs_path = os.path.abspath(path)
    uri = Path(abs_path).as_uri()
    if os.environ.get("BROWSER"):
        return bool(webbrowser.open_new_tab(uri))
    try:
        if sys.platform.startswith("win"):
            os.startfile(abs_path)  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin" and shutil.which("open"):
            subprocess.Popen(["open", abs_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, abs_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        pass
    return bool(webbrowser.open_new_tab(uri))


def maybe_generate_and_open_summary(args):
    if args.no_summary:
        return
    path, error = generate_summary_html()
    if error:
        print("  {}".format(error))
        return
    print("  summary.html を生成しました: {}".format(path))

    should_open = args.open_summary
    if not should_open and sys.stdin.isatty():
        try:
            answer = input("  summary.html をブラウザで開きますか？ [y/N]: ").strip().lower()
            should_open = answer in ("y", "yes", "h", "hai", "はい")
        except EOFError:
            should_open = False
    if should_open:
        if open_html_file(path):
            print("  ブラウザで summary.html を開きました。")
        else:
            print("  ブラウザを起動できませんでした。手動で summary.html を開いてください。")


def run_benchmark(args):
    score_dir = os.path.abspath(args.score_dir)
    os.makedirs(score_dir, exist_ok=True)
    info = collect_system_info()
    if args.threads:
        info["logical_processors"] = args.threads

    print_banner()
    print_system_info(info)
    print_saved_scores(score_dir)
    print("  -- ベンチマーク実行中 (全スレッド100%で負荷をかけます) --")
    print()

    workers = max(1, int(info.get("logical_processors") or 1))
    print("  [1/2] シングルスレッド性能テスト 実行中...", flush=True)
    single_time = run_pool(1, 1, args.work_limit)
    print("        完了: {:.2f} 秒\n".format(single_time), flush=True)
    print("  [2/2] マルチスレッド性能テスト ({} スレッド) 実行中...".format(workers), flush=True)
    multi_time = run_pool(workers, workers, args.work_limit)
    print("        完了: {:.2f} 秒\n".format(multi_time), flush=True)

    single_score = SCORE_FACTOR / single_time
    multi_score = (SCORE_FACTOR * workers) / multi_time
    ratio = single_time / multi_time if multi_time > 0 else 0.0
    gpu_score, gpu_estimated = score_gpu(info)

    print("  ==================================================================")
    print("                  >> BENCHMARK  RESULT  SCORE <<")
    print("  ==================================================================")
    max_score = max([single_score, multi_score] + ([gpu_score] if gpu_score > 0 else []))
    print("  CPU Single {} {:7.0f} pts (優しさの証)".format(bar(single_score, max_score), single_score))
    print("  CPU Multi  {} {:7.0f} pts (全スレッド全力回転)".format(bar(multi_score, max_score), multi_score))
    if gpu_score > 0:
        note = "(VRAM暴力の真価)" + (" ※クロック公称値" if gpu_estimated else "")
        vendor = " [{}]".format(info.get("gpu_vendor")) if info.get("gpu_vendor") else ""
        print("  GPU V-Calc {} {:7.0f} pts {}{}".format(bar(gpu_score, max_score), gpu_score, note, vendor))
    else:
        print("  GPU V-Calc [........................................]   SKIPPED (NVIDIA/AMD未検出 / OOM回避)")
    print("  ------------------------------------------------------------------")
    print("  マルチコア倍率 : {:.2f}x  (Single {:.2f}s / Multi {:.2f}s)".format(ratio, single_time, multi_time))
    print()

    plugin_scores = {} if getattr(args, "no_plugins", False) else run_plugins(info)

    if args.no_save:
        print("  --no-save 指定のためスコア保存をスキップしました。")
    else:
        path = save_score(
            score_dir,
            info,
            {"single": single_score, "multi": multi_score, "gpu": gpu_score},
            single_time,
            multi_time,
            ratio,
            plugin_scores,
        )
        print("  スコアを保存しました: {}".format(path))
        print("  (このJSONファイルを共有すれば結果を比較できます)")
    maybe_generate_and_open_summary(args)
    print()
    print("  ベンチマーク完了。お疲れ様でした！")
    return 0


def fmt_score(value):
    return "{:,.0f}".format(value) if isinstance(value, (int, float)) else "-"


def truncate(value, width):
    value = value or "-"
    return value[: width - 2] + ".." if len(value) > width else value


def load_score_rows(score_dir):
    rows = []
    skipped = 0
    for path in sorted(glob.glob(os.path.join(score_dir, "*.json"))):
        try:
            if os.path.getsize(path) == 0:
                skipped += 1
                continue
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            skipped += 1
            continue
        sysinfo = data.get("system", {})
        best = data.get("best", {})
        runs = data.get("runs", [])
        rows.append({
            "cpu": sysinfo.get("cpu_model") or "Unknown",
            "gpu": sysinfo.get("gpu_name") or "-",
            "single": best.get("cpu_single"),
            "multi": best.get("cpu_multi"),
            "gpu_v": best.get("gpu_vcalc"),
            "runs": len(runs),
        })
    return rows, skipped


def run_summary(args):
    score_dir = os.path.abspath(args.score_dir)
    sort_key = args.sort_opt or args.sort_key or "multi"
    rows, skipped = load_score_rows(score_dir)
    if not rows:
        print("集計対象のスコアがありません。先に `python Tc_bench.py` を実行してください。")
        return 0

    best_field = {"single": "single", "multi": "multi", "gpu": "gpu_v"}[sort_key]
    rows.sort(key=lambda row: (row[best_field] is None, -(row[best_field] or 0)))
    print("  ==================================================================")
    print("                TC BENCH  スコア集計 / ランキング")
    print("  ==================================================================")
    skip_text = "  /  スキップ: {}".format(skipped) if skipped else ""
    print("  並び順: {}  /  登録数: {} 組み合わせ{}\n".format(sort_key, len(rows), skip_text))
    print("  {:>2}  {:<34}{:<22}{:>8}{:>9}{:>9}{:>6}".format("#", "CPU", "GPU", "Single", "Multi", "GPU-V", "Runs"))
    print("  " + "-" * 88)
    for index, row in enumerate(rows, 1):
        print("  {:>2}  {:<34}{:<22}{:>8}{:>9}{:>9}{:>6}".format(
            index,
            truncate(row["cpu"], 34),
            truncate(row["gpu"], 22),
            fmt_score(row["single"]),
            fmt_score(row["multi"]),
            fmt_score(row["gpu_v"]),
            row["runs"],
        ))
    print("  " + "-" * 88)
    print("  * 各値は組み合わせごとのベストスコア。並び替え: python Tc_bench.py summary --sort single|multi|gpu")
    return 0


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("1以上の整数を指定してください")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description="TC Bench CPU/GPU benchmark and score summary")
    sub = parser.add_subparsers(dest="command")

    bench = sub.add_parser("bench", help="CPU/GPU ベンチマークを実行します")
    bench.add_argument("--score-dir", default=DEFAULT_SCORE_DIR, help="スコアJSONの保存先")
    bench.add_argument("--threads", type=positive_int, default=None, help="マルチテストで使うプロセス数")
    bench.add_argument("--work-limit", type=positive_int, default=DEFAULT_WORK_LIMIT, help="CPU負荷量 (既定: %(default)s)")
    bench.add_argument("--no-save", action="store_true", help="結果を score/*.json に保存しない")
    bench.add_argument("--no-summary", action="store_true", help="ベンチ後の summary.html 生成をスキップする")
    bench.add_argument("--open-summary", action="store_true", help="確認なしで summary.html をブラウザで開く")
    bench.add_argument("--no-plugins", action="store_true", help="追加ベンチ (plugins/) を実行しない")
    bench.set_defaults(func=run_benchmark)

    summary = sub.add_parser("summary", help="score/*.json を集計してランキング表示します")
    summary.add_argument("sort_key", nargs="?", choices=SORT_KEYS, help="並び順: single / multi / gpu")
    summary.add_argument("--sort", dest="sort_opt", choices=SORT_KEYS, help="並び順: single / multi / gpu")
    summary.add_argument("--score-dir", default=DEFAULT_SCORE_DIR, help="スコアJSONの保存先")
    summary.set_defaults(func=run_summary)

    plugin = sub.add_parser("plugin", help="追加ベンチ(プラグイン)の一覧/導入/削除")
    plugin.add_argument("action", nargs="?", choices=("list", "install", "remove"), default="list",
                        help="list / install <名前> / remove <名前>")
    plugin.add_argument("name", nargs="?", help="プラグイン名 (install / remove 時)")
    plugin.set_defaults(func=run_plugin_command)

    return parser


def normalize_argv(argv):
    if not argv:
        return ["bench"]
    if argv[0] in ("-h", "--help", "bench", "summary", "plugin"):
        return argv
    return ["bench"] + argv


def main(argv=None):
    configure_stdio()
    init_color()
    parser = build_parser()
    args = parser.parse_args(normalize_argv(list(argv if argv is not None else sys.argv[1:])))
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
