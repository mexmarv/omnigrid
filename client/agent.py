"""
Provider daemon: announces spare CPU/RAM/GPU (and any configured LLM/VLM
backends) to the hub, polls for jobs it's capable of running, executes
them, and reports the result back.

Two separate execution paths, matching the security/reliability split
this project draws between them:
  - tensor_op / onnx_infer: fixed, short-lived operations -- run in an
    isolated, wall-clock-limited subprocess (sandbox.py), same as before.
  - llm_infer:<model> / vlm_infer:<model>: routed directly to a persistent,
    already-warm InferenceBackend (client/inference/) that stays loaded
    across every job -- never spawned or reloaded per request.

Usage:
    python agent.py --name "your name" --cpu-cores 2 --ram-mb 2048
    python agent.py --name "your name" --cpu-cores 2 --ram-mb 2048 --ignore-idle --once

    # persistent Ollama/llama.cpp backends, see models.example.yaml
    python agent.py --name "your name" --cpu-cores 4 --ram-mb 8192 \\
        --models-config models.yaml
"""

import argparse
import asyncio
import os
import platform
import subprocess
import time

import psutil
import requests

import credentials
import handlers
import sandbox
from inference import (
    BackendError,
    ConfigError,
    InferenceManager,
    ValidationError,
    legacy_llamacpp_config,
    load_model_configs,
    merge_configs,
    normalize_generate_payload,
)
from safe_io import decode_json_payload, encode_json_result

IDLE_CPU_THRESHOLD = 30.0  # percent; only fetch work below this, unless --ignore-idle

# A provider-side ceiling on how long a single generation job may run,
# regardless of what the job itself requests -- consumer-provided timeouts
# are never trusted beyond this (see inference/schema.py for the same
# principle applied to token/parameter limits).
MAX_GENERATION_TIMEOUT_S = 900


def detect_gpu():
    """Best-effort GPU detection. Returns (model, vram_mb_or_None).

    Tries NVIDIA (nvidia-smi) first, then Apple Silicon (unified memory, so
    there's no separate VRAM figure to report -- None instead).
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


def build_model_configs(args, gpu_model):
    """Merges --models-config YAML with the legacy single-model CLI flags.
    Raises SystemExit with a clear message on any invalid configuration --
    this always runs before any backend is started."""
    try:
        yaml_configs = load_model_configs(args.models_config)
    except ConfigError as exc:
        raise SystemExit(f"Invalid --models-config: {exc}")

    legacy_configs = []
    if args.llm_model_path:
        if not args.llm_model_name:
            raise SystemExit("--llm-model-name is required when --llm-model-path is set.")
        gpu_layers = args.gpu_layers if args.gpu_layers is not None else (-1 if gpu_model else 0)
        legacy_configs.append(legacy_llamacpp_config(
            public_name=args.llm_model_name, model_path=args.llm_model_path, n_gpu_layers=gpu_layers,
        ))

    if args.vlm_model_path:
        if not args.vlm_mmproj_path:
            raise SystemExit("--vlm-mmproj-path is required when --vlm-model-path is set.")
        if not args.vlm_model_name:
            raise SystemExit("--vlm-model-name is required when --vlm-model-path is set.")
        legacy_configs.append(legacy_llamacpp_config(
            public_name=args.vlm_model_name, model_path=args.vlm_model_path,
            mmproj_path=args.vlm_mmproj_path, n_gpu_layers=-1,
        ))

    try:
        return merge_configs(yaml_configs, legacy_configs)
    except ConfigError as exc:
        raise SystemExit(f"Invalid model configuration: {exc}")


async def run_generation_job(job: dict, manager: InferenceManager):
    """Runs one llm_infer:<model>/vlm_infer:<model> job against its
    persistent backend. Returns (status, result_b64_or_None, error_or_None,
    compute_seconds) -- the same contract as sandbox.run(), so agent.py's
    reporting code doesn't need to know which path a job took.
    """
    start = time.monotonic()
    task_type = job["task_type"]
    family, _, model_name = task_type.partition(":")

    model_cfg = manager.model_config(model_name)
    if model_cfg is None or model_name not in manager.available_models():
        return "failed", None, f"No healthy backend currently hosts '{model_name}'.", time.monotonic() - start

    try:
        payload = decode_json_payload(job["payload_b64"])
    except Exception as exc:
        return "failed", None, f"Malformed payload: {exc}", time.monotonic() - start

    try:
        request = normalize_generate_payload(payload, model_cfg, allow_images=(family == "vlm_infer"))
    except ValidationError as exc:
        return "failed", None, str(exc), time.monotonic() - start

    job_timeout_s = min(int(job.get("timeout_s") or MAX_GENERATION_TIMEOUT_S), MAX_GENERATION_TIMEOUT_S)
    try:
        response = await asyncio.wait_for(manager.generate(model_name, request), timeout=job_timeout_s)
    except asyncio.TimeoutError:
        return "failed", None, f"Generation exceeded {job_timeout_s}s.", time.monotonic() - start
    except BackendError as exc:
        return "failed", None, str(exc), time.monotonic() - start
    except Exception as exc:  # deliberately broad: a bad job must not crash the agent
        return "failed", None, f"{type(exc).__name__}: {exc}", time.monotonic() - start

    compute_seconds = time.monotonic() - start
    result = {"text": response.text}
    if response.input_tokens is not None:
        result["input_tokens"] = response.input_tokens
    if response.output_tokens is not None:
        result["output_tokens"] = response.output_tokens
    return "done", encode_json_result(result), None, compute_seconds


async def main_async():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", help="account name to credit/debit -- omit if using --api-key")
    parser.add_argument("--email",
                         help="only needed the first time --name registers on this coordinator -- "
                              "used solely for reset.php (reissue a lost key / delete the account)")
    parser.add_argument("--api-key",
                         help="already have a key (e.g. from register.php)? Pass it directly and "
                              "skip --name/--email entirely.")
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--cpu-cores", type=float, required=True,
                         help="how many CPU cores you're willing to donate")
    parser.add_argument("--ram-mb", type=int, required=True,
                         help="how much RAM (MB) you're willing to donate")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--ignore-idle", action="store_true",
                         help="fetch work even if the machine isn't idle (useful for testing)")
    parser.add_argument("--once", action="store_true", help="process a single job and exit")
    parser.add_argument("--models-config",
                         default=os.environ.get("OMNIGRID_MODELS_CONFIG"),
                         help="path to a YAML file of persistent Ollama/llama.cpp backends to host "
                              "(see client/models.example.yaml). Also settable via "
                              "OMNIGRID_MODELS_CONFIG.")
    parser.add_argument("--llm-model-path",
                         help="path to a GGUF model file to host for llm_infer, served by a "
                              "persistent llama-server worker (kept warm across jobs, not "
                              "reloaded per request)")
    parser.add_argument("--llm-model-name",
                         help="short name for the model, advertised as task_type "
                              "'llm_infer:<name>' (required if --llm-model-path is set)")
    parser.add_argument("--gpu-layers", type=int, default=None,
                        help="LLM layers to offload to GPU (-1 = all, 0 = CPU-only). "
                             "Defaults to -1 if a GPU was detected, else 0.")
    parser.add_argument("--vlm-model-path", help="path to a GGUF vision-language model file to host")
    parser.add_argument("--vlm-mmproj-path",
                         help="path to that model's vision projector (mmproj) GGUF file "
                              "(required if --vlm-model-path is set)")
    parser.add_argument("--vlm-model-name",
                         help="short name for the model, advertised as task_type "
                              "'vlm_infer:<name>' (required if --vlm-model-path is set)")
    args = parser.parse_args()

    if not args.api_key and not args.name:
        raise SystemExit("Pass either --api-key, or --name (and --email the first time it registers).")

    host_cores = psutil.cpu_count(logical=True)
    host_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
    if args.cpu_cores > host_cores or args.ram_mb > host_ram_mb:
        raise SystemExit(
            f"Can't donate more than this machine has: {host_cores} cores / {host_ram_mb} MB RAM."
        )

    gpu_model, gpu_vram_mb = detect_gpu()
    model_configs = build_model_configs(args, gpu_model)

    manager = InferenceManager(model_configs) if model_configs else None
    task_types = list(handlers.installed_task_types())  # tensor_op, onnx_infer

    if manager is not None:
        health = await manager.start()
        for name, h in health.items():
            print(f"model '{name}': {'healthy' if h.healthy else 'UNHEALTHY -- ' + h.detail}")
        for name in manager.available_models():
            cfg = manager.model_config(name)
            family = "vlm_infer" if cfg.vision else "llm_infer"
            task_types.append(f"{family}:{name}")

    print(f"Installed handlers/task_types: {task_types}")
    if gpu_model:
        print(f"GPU detected: {gpu_model}" + (f" ({gpu_vram_mb} MB)" if gpu_vram_mb else ""))

    try:
        api_key = args.api_key or await asyncio.to_thread(
            credentials.get_api_key, args.coordinator, args.name, args.email
        )
        auth_headers = {"Authorization": f"Bearer {api_key}"}

        resp = await asyncio.to_thread(
            requests.post, f"{args.coordinator}/api/providers_announce.php", headers=auth_headers, json={
                "cpu_cores": args.cpu_cores,
                "ram_mb": args.ram_mb,
                "gpu_model": gpu_model,
                "gpu_vram_mb": gpu_vram_mb,
                "task_types": task_types,
            },
        )
        resp.raise_for_status()
        provider_id = resp.json()["provider_id"]
        print(f"Registered as provider #{provider_id}. Donating {args.cpu_cores} cores / "
              f"{args.ram_mb} MB RAM. Only working while this machine looks idle.")

        while True:
            if not args.ignore_idle and not await asyncio.to_thread(is_idle):
                await asyncio.sleep(args.poll_interval)
                continue

            # re-announce doubles as a heartbeat so we drop out of the directory if this exits
            await asyncio.to_thread(
                requests.post, f"{args.coordinator}/api/providers_announce.php", headers=auth_headers, json={
                    "provider_id": provider_id,
                    "cpu_cores": args.cpu_cores, "ram_mb": args.ram_mb,
                    "gpu_model": gpu_model, "gpu_vram_mb": gpu_vram_mb, "task_types": task_types,
                },
            )

            job_resp = await asyncio.to_thread(
                requests.get, f"{args.coordinator}/api/providers_next_job.php",
                params={"provider_id": provider_id}, headers=auth_headers,
            )
            if job_resp.status_code == 204:
                await asyncio.sleep(args.poll_interval)
                continue
            job_resp.raise_for_status()
            job = job_resp.json()

            print(f"Running job #{job['id']} ({job['task_type']})...")
            family = job["task_type"].split(":", 1)[0]
            if manager is not None and family in ("llm_infer", "vlm_infer"):
                status, result_b64, error, compute_seconds = await run_generation_job(job, manager)
            else:
                status, result_b64, error, compute_seconds = await asyncio.to_thread(
                    sandbox.run, job["task_type"], job["payload_b64"], job["ram_limit_mb"], job["timeout_s"],
                )

            if status == "done":
                result_resp = await asyncio.to_thread(
                    requests.post, f"{args.coordinator}/api/jobs_result.php", headers=auth_headers, json={
                        "job_id": job["id"], "result_format": "json",
                        "result_b64": result_b64, "compute_seconds": compute_seconds,
                    },
                )
                result_resp.raise_for_status()
                print(f"job #{job['id']} done in {compute_seconds:.2f}s")
            else:
                failure_resp = await asyncio.to_thread(
                    requests.post, f"{args.coordinator}/api/jobs_failure.php", headers=auth_headers, json={
                        "job_id": job["id"], "error": error,
                    },
                )
                failure_resp.raise_for_status()
                print(f"job #{job['id']} failed: {error}")

            if args.once:
                return
    finally:
        if manager is not None:
            await manager.close()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
