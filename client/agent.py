"""
Provider daemon: announces spare CPU/RAM/GPU to the hub, polls for jobs it's
capable of running (only task_types it has handlers installed for), executes
them in an isolated subprocess, and reports the result back.

Usage:
    python agent.py --name "your name" --cpu-cores 2 --ram-mb 2048
    python agent.py --name "your name" --cpu-cores 2 --ram-mb 2048 --ignore-idle --once
"""

import argparse
import os
import platform
import subprocess
import time

import psutil
import requests

import credentials
import handlers
import sandbox

try:
    from handlers.llm_infer import GPU_LAYERS_ENV, MODEL_PATH_ENV
except ImportError:
    MODEL_PATH_ENV = "OMNIGRID_LLM_MODEL_PATH"
    GPU_LAYERS_ENV = "OMNIGRID_LLM_GPU_LAYERS"

IDLE_CPU_THRESHOLD = 30.0  # percent; only fetch work below this, unless --ignore-idle


def detect_gpu():
    """Best-effort GPU detection. Returns (model, vram_mb_or_None).

    Tries NVIDIA (nvidia-smi) first, then Apple Silicon (unified memory, so
    there's no separate VRAM figure to report -- None instead). Verified for
    real on Apple Silicon: llama.cpp's own device-init log confirms Metal is
    engaged and all layers offload when n_gpu_layers is set (see llm_infer.py).
    """
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            timeout=5, text=True,
        )
        name, mem = out.strip().split("\n")[0].split(",")
        return name.strip(), int(mem.strip())
    except Exception:
        pass

    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            chip = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5, text=True
            ).strip()
        except Exception:
            chip = "Apple Silicon"
        return f"{chip} (Metal)", None

    return None, None


def is_idle() -> bool:
    return psutil.cpu_percent(interval=1.0) < IDLE_CPU_THRESHOLD


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="account name to credit/debit")
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--cpu-cores", type=float, required=True,
                         help="how many CPU cores you're willing to donate")
    parser.add_argument("--ram-mb", type=int, required=True,
                         help="how much RAM (MB) you're willing to donate")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--ignore-idle", action="store_true",
                         help="fetch work even if the machine isn't idle (useful for testing)")
    parser.add_argument("--once", action="store_true", help="process a single job and exit")
    parser.add_argument("--llm-model-path", help="path to a GGUF model file to host for llm_infer")
    parser.add_argument("--llm-model-name",
                         help="short name for the model, advertised as task_type "
                              "'llm_infer:<name>' (required if --llm-model-path is set)")
    parser.add_argument("--gpu-layers", type=int, default=None,
                        help="LLM layers to offload to GPU (-1 = all, 0 = CPU-only). "
                             "Defaults to -1 if a GPU was detected, else 0.")
    args = parser.parse_args()

    host_cores = psutil.cpu_count(logical=True)
    host_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
    if args.cpu_cores > host_cores or args.ram_mb > host_ram_mb:
        raise SystemExit(
            f"Can't donate more than this machine has: {host_cores} cores / {host_ram_mb} MB RAM."
        )

    gpu_model, gpu_vram_mb = detect_gpu()
    # bare "llm_infer" is never directly requestable -- consumers always ask for a
    # specific "llm_infer:<model-name>"; drop it here and add the real variant below.
    task_types = [t for t in handlers.installed_task_types() if t != "llm_infer"]

    if args.llm_model_path:
        if not args.llm_model_name:
            raise SystemExit("--llm-model-name is required when --llm-model-path is set.")
        if handlers.get_handler("llm_infer") is None:
            raise SystemExit(
                "llama-cpp-python isn't installed, so this agent can't serve llm_infer. "
                "pip install llama-cpp-python and try again."
            )
        gpu_layers = args.gpu_layers if args.gpu_layers is not None else (-1 if gpu_model else 0)
        os.environ[MODEL_PATH_ENV] = args.llm_model_path
        os.environ[GPU_LAYERS_ENV] = str(gpu_layers)
        task_types.append(f"llm_infer:{args.llm_model_name}")

    print(f"Installed handlers: {task_types}")
    if gpu_model:
        print(f"GPU detected: {gpu_model}" + (f" ({gpu_vram_mb} MB)" if gpu_vram_mb else ""))
        if args.llm_model_path:
            print(f"LLM GPU offload: n_gpu_layers={os.environ[GPU_LAYERS_ENV]}")

    api_key = credentials.get_api_key(args.coordinator, args.name)
    auth_headers = {"Authorization": f"Bearer {api_key}"}

    resp = requests.post(f"{args.coordinator}/api/providers_announce.php", headers=auth_headers, json={
        "cpu_cores": args.cpu_cores,
        "ram_mb": args.ram_mb,
        "gpu_model": gpu_model,
        "gpu_vram_mb": gpu_vram_mb,
        "task_types": task_types,
    })
    resp.raise_for_status()
    provider_id = resp.json()["provider_id"]
    print(f"Registered as provider #{provider_id}. Donating {args.cpu_cores} cores / "
          f"{args.ram_mb} MB RAM. Only working while this machine looks idle.")

    while True:
        if not args.ignore_idle and not is_idle():
            time.sleep(args.poll_interval)
            continue

        # re-announce doubles as a heartbeat so we drop out of the directory if this exits
        requests.post(f"{args.coordinator}/api/providers_announce.php", headers=auth_headers, json={
            "provider_id": provider_id,
            "cpu_cores": args.cpu_cores, "ram_mb": args.ram_mb,
            "gpu_model": gpu_model, "gpu_vram_mb": gpu_vram_mb, "task_types": task_types,
        })

        job_resp = requests.get(
            f"{args.coordinator}/api/providers_next_job.php",
            params={"provider_id": provider_id}, headers=auth_headers,
        )
        if job_resp.status_code == 204:
            time.sleep(args.poll_interval)
            continue
        job_resp.raise_for_status()
        job = job_resp.json()

        print(f"Running job #{job['id']} ({job['task_type']})...")
        status, result_b64, error, compute_seconds = sandbox.run(
            job["task_type"], job["payload_b64"], job["ram_limit_mb"], job["timeout_s"],
        )

        if status == "done":
            requests.post(f"{args.coordinator}/api/jobs_result.php", headers=auth_headers, json={
                "job_id": job["id"], "result_format": "json",
                "result_b64": result_b64, "compute_seconds": compute_seconds,
            }).raise_for_status()
            print(f"job #{job['id']} done in {compute_seconds:.2f}s")
        else:
            requests.post(f"{args.coordinator}/api/jobs_failure.php", headers=auth_headers, json={
                "job_id": job["id"], "error": error,
            }).raise_for_status()
            print(f"job #{job['id']} failed: {error}")

        if args.once:
            return


if __name__ == "__main__":
    main()
