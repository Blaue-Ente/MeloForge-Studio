import platform
import shutil
import subprocess

import psutil

from app.config import Settings


def _nvidia_vram() -> tuple[float | None, float | None]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None, None
    try:
        result = subprocess.run(
            [executable, "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        first = result.stdout.strip().splitlines()[0]
        total, free = [float(value.strip()) / 1024 for value in first.split(",")]
        return round(total, 2), round(free, 2)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None, None


def get_hardware_status(settings: Settings) -> dict:
    memory = psutil.virtual_memory()
    vram_total, vram_free = _nvidia_vram()
    free_ram_gb = round(memory.available / (1024**3), 2)
    configured = settings.local_llm_enabled and bool(settings.local_llm_model)
    enough_ram = free_ram_gb >= settings.local_min_free_ram_gb
    return {
        "platform": platform.platform(),
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_total_gb": round(memory.total / (1024**3), 2),
        "ram_available_gb": free_ram_gb,
        "gpu": {
            "detected": vram_total is not None,
            "vendor": "NVIDIA" if vram_total is not None else None,
            "vram_total_gb": vram_total,
            "vram_available_gb": vram_free,
        },
        "local_llm": {
            "configured": configured,
            "resource_check_passed": configured and enough_ram,
            "recommended_profile": "small-quantized-cpu-gpu-offload",
            "note": "Advisory check only; actual model loading and inference must be tested.",
        },
    }
