#!/usr/bin/env python3

"""
Environment Profiler for the Batcave.

Fingerprints the host machine at boot and writes a capability profile so
every agent (Robin, Sentinel, Lucius) can adapt behavior to the hardware.

Profile includes:
    - CPU: cores, frequency, architecture
    - RAM: total, available, percent used
    - GPU: type, VRAM (if detectable), driver
    - Disk: total, free, percent used per drive
    - Ollama: running status, available models with sizes
    - Python: version, key packages installed
    - Network: connectivity, external IP (optional)
    - Tools: git, node, npm, ffmpeg, playwright availability

Output: rudy-data/environment-profile.json

Consumers:
    - Robin: reads profile at boot to select model (7b vs 14b)
    - Sentinel: reads profile for health thresholds
    - Lucius: reads profile for audit context

Enables the "rollout" pattern: same codebase deploys to any machine
and self-configures based on detected capabilities.

Lucius Gate: LG-003 — No new dependencies. Uses only stdlib + psutil
(already installed). APPROVED, Lite Review.
"""

import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("batcave.environment_profiler")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROFILE_OUTPUT = Path(__file__).resolve().parent.parent / "rudy-data" / "environment-profile.json"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Model selection thresholds
GPU_VRAM_THRESHOLD_14B = 8000   # MB - need ~8GB VRAM for 14b models (8188MB on RTX 4060)
RAM_THRESHOLD_14B = 16384       # MB - need 16GB+ RAM for 14b (CPU inference)
RAM_THRESHOLD_7B = 8192         # MB - need 8GB+ for 7b

# ---------------------------------------------------------------------------
# CPU Profiling
# ---------------------------------------------------------------------------

def profile_cpu() -> dict:
    """Profile CPU capabilities."""
    info = {
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "physical_cores": os.cpu_count(),  # logical cores
        "system": platform.system(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }

    # Try to get more detail on Windows
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            info["cpu_name"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            info["cpu_mhz"] = winreg.QueryValueEx(key, "~MHz")[0]
            winreg.CloseKey(key)
        except Exception:
            pass

    return info

# ---------------------------------------------------------------------------
# Memory Profiling
# ---------------------------------------------------------------------------

def profile_memory() -> dict:
    """Profile RAM availability."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "total_mb": round(mem.total / (1024 * 1024)),
            "available_mb": round(mem.available / (1024 * 1024)),
            "used_percent": mem.percent,
            "swap_total_mb": round(psutil.swap_memory().total / (1024 * 1024)),
            "swap_used_percent": psutil.swap_memory().percent,
        }
    except ImportError:
        # Fallback without psutil
        return {"error": "psutil not available", "note": "pip install psutil"}

# ---------------------------------------------------------------------------
# GPU Profiling
# ---------------------------------------------------------------------------

def profile_gpu() -> dict:
    """Detect GPU type, VRAM, and driver."""
    gpu_info = {"detected": False, "type": "unknown", "vram_mb": 0}

    # Try nvidia-smi first
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            gpu_info = {
                "detected": True,
                "type": "nvidia_discrete",
                "name": parts[0].strip(),
                "vram_mb": int(parts[1].strip()) if len(parts) > 1 else 0,
                "driver": parts[2].strip() if len(parts) > 2 else "unknown",
            }
            return gpu_info
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try Windows WMI for Intel/AMD iGPU
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                if data:
                    gpu = data[0]
                    adapter_ram = gpu.get("AdapterRAM", 0) or 0
                    name = gpu.get("Name", "Unknown")
                    gpu_info = {
                        "detected": True,
                        "type": "igpu" if "Intel" in name or "UHD" in name else "discrete",
                        "name": name,
                        "vram_mb": round(adapter_ram / (1024 * 1024)) if adapter_ram else 0,
                        "driver": gpu.get("DriverVersion", "unknown"),
                        "shared_memory": "Intel" in name or "UHD" in name,
                    }
                    return gpu_info
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    return gpu_info

# ---------------------------------------------------------------------------
# Disk Profiling
# ---------------------------------------------------------------------------

def profile_disk() -> dict:
    """Profile disk space on all drives."""
    drives = {}

    if platform.system() == "Windows":
        # Check common Windows drive letters
        for letter in "CDEFGH":
            path = f"{letter}:\\"
            if os.path.exists(path):
                try:
                    usage = shutil.disk_usage(path)
                    drives[f"{letter}:"] = {
                        "total_gb": round(usage.total / (1024**3), 1),
                        "free_gb": round(usage.free / (1024**3), 1),
                        "used_percent": round((usage.used / usage.total) * 100, 1),
                    }
                except OSError:
                    pass
    else:
        # Linux/Mac
        try:
            usage = shutil.disk_usage("/")
            drives["/"] = {
                "total_gb": round(usage.total / (1024**3), 1),
                "free_gb": round(usage.free / (1024**3), 1),
                "used_percent": round((usage.used / usage.total) * 100, 1),
            }
        except OSError:
            pass

    return drives

# ---------------------------------------------------------------------------
# Ollama Profiling
# ---------------------------------------------------------------------------

def profile_ollama() -> dict:
    """Check Ollama status and available models."""
    ollama_info = {"running": False, "host": OLLAMA_HOST, "models": []}

    # Check if Ollama is running
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            ollama_info["running"] = True
            ollama_info["models"] = [
                {
                    "name": m.get("name", ""),
                    "size_mb": round(m.get("size", 0) / (1024 * 1024)),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                    "quantization": m.get("details", {}).get("quantization_level", ""),
                    "family": m.get("details", {}).get("family", ""),
                }
                for m in models
            ]
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        pass

    return ollama_info

# ---------------------------------------------------------------------------
# Tools Detection
# ---------------------------------------------------------------------------

def profile_tools() -> dict:
    """Detect availability of key tools."""
    tools = {}

    checks = {
        "git": [r"C:\Program Files\Git\cmd\git.exe", "--version"],
        "python": [sys.executable, "--version"],
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
        "playwright": [sys.executable, "-c", "import playwright; print(playwright.__version__)"],
        "ffmpeg": ["ffmpeg", "-version"],
    }

    for tool_name, cmd in checks.items():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = result.stdout.strip().split("\n")[0]
                tools[tool_name] = {"available": True, "version": version}
            else:
                tools[tool_name] = {"available": False}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            tools[tool_name] = {"available": False}

    # Check key Python packages
    packages = ["langgraph", "langchain_ollama", "playwright", "psutil", "pydantic"]
    python_packages = {}
    for pkg in packages:
        try:
            mod = __import__(pkg)
            version = getattr(mod, "__version__", "installed")
            python_packages[pkg] = version
        except ImportError:
            python_packages[pkg] = None

    tools["python_packages"] = python_packages
    return tools

# ---------------------------------------------------------------------------
# Network Profiling
# ---------------------------------------------------------------------------

def profile_network() -> dict:
    """Basic network connectivity check."""
    net_info = {
        "hostname": socket.gethostname(),
        "internet_access": False,
    }

    # Check internet connectivity
    try:
        urllib.request.urlopen("https://httpbin.org/get", timeout=5)
        net_info["internet_access"] = True
    except Exception:
        # Try a fallback
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            net_info["internet_access"] = True
        except Exception:
            pass

    return net_info

# ---------------------------------------------------------------------------
# Model Recommendation Engine
# ---------------------------------------------------------------------------

def recommend_model(profile: dict) -> dict:
    """
    Based on hardware profile, recommend the best Ollama model for Robin.

    Decision tree:
    1. If discrete GPU with 8GB+ VRAM -> 14b model (fast inference)
    2. If 16GB+ RAM and no good GPU -> 14b model (slow but capable)
    3. If 8GB+ RAM -> 7b model (standard)
    4. If <8GB RAM -> 3b model or flag as underpowered
    """
    ram_mb = profile.get("memory", {}).get("total_mb", 0)
    gpu = profile.get("gpu", {})
    vram_mb = gpu.get("vram_mb", 0)
    is_igpu = gpu.get("shared_memory", False) or gpu.get("type") == "igpu"
    ollama_models = [m["name"] for m in profile.get("ollama", {}).get("models", [])]

    recommendation = {
        "primary_model": "qwen2.5:7b",
        "reason": "default fallback",
        "alternatives": [],
        "hardware_tier": "standard",
    }

    # Tier 1: Discrete GPU with good VRAM
    if not is_igpu and vram_mb >= GPU_VRAM_THRESHOLD_14B:
        recommendation["hardware_tier"] = "high"
        recommendation["primary_model"] = "qwen2.5:14b"
        recommendation["reason"] = f"Discrete GPU with {vram_mb}MB VRAM supports 14b inference"
        recommendation["alternatives"] = ["deepseek-r1:14b", "qwen2.5:7b"]

    # Tier 2: Lots of RAM, CPU inference
    elif ram_mb >= RAM_THRESHOLD_14B:
        recommendation["hardware_tier"] = "medium-high"
        recommendation["primary_model"] = "qwen2.5:14b"
        recommendation["reason"] = f"{ram_mb}MB RAM supports 14b via CPU inference (slower)"
        recommendation["alternatives"] = ["qwen2.5:7b", "deepseek-r1:8b"]

    # Tier 3: Standard (W1's likely tier)
    elif ram_mb >= RAM_THRESHOLD_7B:
        recommendation["hardware_tier"] = "standard"
        recommendation["primary_model"] = "qwen2.5:7b"
        recommendation["reason"] = f"{ram_mb}MB RAM with {'shared iGPU' if is_igpu else 'GPU'} - 7b optimal (RAM constrained)"
        recommendation["alternatives"] = ["deepseek-r1:8b"]

    # Tier 4: Underpowered
    else:
        recommendation["hardware_tier"] = "low"
        recommendation["primary_model"] = "qwen2.5:3b"
        recommendation["reason"] = f"Only {ram_mb}MB RAM - 3b model recommended"
        recommendation["alternatives"] = []
        recommendation["warning"] = "Hardware below recommended minimums for autonomous agent work"

    # Cross-check with actually available models
    if ollama_models:
        if recommendation["primary_model"] not in ollama_models:
            # Fall back to best available
            for alt in recommendation["alternatives"]:
                if alt in ollama_models:
                    recommendation["primary_model"] = alt
                    recommendation["reason"] += f" (recommended model not installed, using {alt})"
                    break
            else:
                if ollama_models:
                    recommendation["primary_model"] = ollama_models[0]
                    recommendation["reason"] += f" (fallback to first available: {ollama_models[0]})"

        recommendation["available_models"] = ollama_models

    return recommendation

# ---------------------------------------------------------------------------
# Main Profiler
# ---------------------------------------------------------------------------

def run_profile() -> dict:
    """Run full environment profile and return results."""
    start = time.time()

    profile = {
        "timestamp": datetime.now().isoformat(),
        "profiler_version": "1.0.0",
        "cpu": profile_cpu(),
        "memory": profile_memory(),
        "gpu": profile_gpu(),
        "disk": profile_disk(),
        "ollama": profile_ollama(),
        "tools": profile_tools(),
        "network": profile_network(),
    }

    # Generate model recommendation
    profile["model_recommendation"] = recommend_model(profile)

    # Timing
    profile["profile_duration_ms"] = int((time.time() - start) * 1000)

    return profile

def save_profile(profile: dict, path: Optional[Path] = None) -> Path:
    """Save profile to JSON file."""
    output = path or PROFILE_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
    logger.info(f"Environment profile saved to {output}")
    return output

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("Batcave Environment Profiler v1.0")
    print("=" * 60)

    profile = run_profile()

    # Print summary
    cpu = profile["cpu"]
    mem = profile["memory"]
    gpu = profile["gpu"]
    ollama = profile["ollama"]
    rec = profile["model_recommendation"]

    print(f"\nCPU: {cpu.get('cpu_name', cpu.get('processor', 'unknown'))}")
    print(f"     {cpu.get('physical_cores', '?')} cores")
    print(f"RAM: {mem.get('total_mb', '?')}MB total, {mem.get('available_mb', '?')}MB available ({mem.get('used_percent', '?')}% used)")
    print(f"GPU: {gpu.get('name', 'not detected')} ({gpu.get('vram_mb', 0)}MB VRAM, {'shared' if gpu.get('shared_memory') else 'dedicated'})")

    print(f"\nOllama: {'RUNNING' if ollama['running'] else 'NOT RUNNING'}")
    if ollama["models"]:
        for m in ollama["models"]:
            print(f"  - {m['name']} ({m['size_mb']}MB, {m.get('parameter_size', '?')})")

    print("\nDisk:")
    for drive, info in profile["disk"].items():
        print(f"  {drive} {info['free_gb']}GB free / {info['total_gb']}GB total ({info['used_percent']}% used)")

    print("\nModel Recommendation:")
    print(f"  Tier: {rec['hardware_tier']}")
    print(f"  Model: {rec['primary_model']}")
    print(f"  Reason: {rec['reason']}")
    if rec.get("alternatives"):
        print(f"  Alternatives: {', '.join(rec['alternatives'])}")

    print(f"\nProfile generated in {profile['profile_duration_ms']}ms")

    # Save
    output = save_profile(profile)
    print(f"Saved to: {output}")

    print("\n" + "=" * 60)
