import importlib
import json
import os
import sys
import time
import requests
import boto3
import platform
import socket
from datetime import datetime, timezone

# --------------------------------------------
# Worker Configuration
# --------------------------------------------
FLASK_HOST = os.getenv("FLASK_HOST", "localhost")
FLASK_PORT = os.getenv("FLASK_PORT", "5000")

MINIO_HOST = os.getenv("MINIO_HOST", "localhost")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin123")

INPUT_BUCKET = "inputs"
RESULT_BUCKET = "results"

WORKER_ID = socket.gethostname()

# --------------------------------------------
# Strategy Loader
# --------------------------------------------
def load_task_runner(cli_strategy=None):
    """
    Loads strategy as a Python module from task_running_strategies/.
    Lookup order:
        1. CLI argument (python3 worker.py <strategy>)
        2. TEMP_TASK_RUNNER (env override)
        3. task_config.json ("active_task_runner")
        4. fallback = task_runner_default
    """
    # 1. CLI argument
    if cli_strategy:
        module_name = cli_strategy
    else:
        # 2. TEMP override
        env_override = os.getenv("TEMP_TASK_RUNNER")
        if env_override:
            module_name = env_override
        else:
            # 3. Load from task_config.json
            try:
                with open("task_config.json", "r") as f:
                    cfg = json.load(f)
                    module_name = cfg["active_task_runner"]
            except:
                # 4. fallback
                module_name = "task_runner_default"

    print(f"[WORKER] Using task runner: {module_name}")

    # convert module name → package path
    module_path = f"task_running_strategies.{module_name}"

    try:
        return importlib.import_module(module_path)
    except Exception as e:
        print(f"[WORKER] ERROR loading strategy '{module_path}': {e}")
        raise


# Load strategy (but instance created later)
strategy_name = sys.argv[1] if len(sys.argv) > 1 else None
strategy_module = load_task_runner(strategy_name)

# --------------------------------------------
# MinIO Client
# --------------------------------------------
s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{MINIO_HOST}:9000",
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
)

# --------------------------------------------
# Job Interactions
# --------------------------------------------
def claim_job():
    try:
        resp = requests.post(
            f"http://{FLASK_HOST}:{FLASK_PORT}/claim_job",
            timeout=3
        )
        return resp.json()
    except Exception as e:
        print("[WORKER] Error claiming job:", e)
        return None


def upload_result(job_id, path):
    url = f"http://{FLASK_HOST}:{FLASK_PORT}/upload_result/{job_id}"
    with open(path, "rb") as f:
        files = {"file": f}
        return requests.post(url, files=files).json()


# --------------------------------------------
# Registration + Heartbeat
# --------------------------------------------
def register_with_master():
    payload = {
        "worker_id": WORKER_ID,
        "hostname": WORKER_ID,
        "ip": socket.gethostbyname(WORKER_ID),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "kernel": platform.release(),
        "task_runner": strategy_module.__name__
    }

    try:
        requests.post(
            f"http://{FLASK_HOST}:{FLASK_PORT}/register_worker",
            json=payload
        )
        print("[WORKER] Registered with master.")
    except Exception as e:
        print("[WORKER] Failed to register worker:", e)


def send_heartbeat():
    try:
        requests.post(
            f"http://{FLASK_HOST}:{FLASK_PORT}/heartbeat",
            json={
                "worker_id": WORKER_ID,
                "last_heartbeat": datetime.now(timezone.utc).isoformat()
            }
        )
    except:
        pass


# --------------------------------------------
# Main Worker Loop (Strategy Pattern)
# --------------------------------------------
def run_worker(strategy_name=None):
    print("[WORKER] ----------------------------------------")
    print(f"[WORKER] Worker ID      : {WORKER_ID}")
    print(f"[WORKER] Master         : {FLASK_HOST}:{FLASK_PORT}")
    print(f"[WORKER] Strategy       : {strategy_module.__name__}")
    print("[WORKER] ----------------------------------------")

    register_with_master()

    # Create working directory
    TASK_DIR = "current_task_files"
    os.makedirs(TASK_DIR, exist_ok=True)

    while True:
        send_heartbeat()

        job = claim_job()

        if not job or job.get("message") == "No jobs in any queue":
            time.sleep(2)
            continue

        job_id = job["id"]
        filename = job["filename"]

        print(f"[WORKER] Claimed job {job_id}")

        # Paths inside working directory
        input_path = os.path.join(TASK_DIR, f"input_{job_id}")
        output_path = os.path.join(TASK_DIR, f"result_{job_id}.txt")

        # Clear task directory
        for f in os.listdir(TASK_DIR):
            os.remove(os.path.join(TASK_DIR, f))

        # -----------------------
        # Download
        # -----------------------
        print("[WORKER] Downloading input file...")
        try:
            s3.download_file(INPUT_BUCKET, filename, input_path)
        except Exception as e:
            print("[WORKER] Failed to download input:", e)
            continue

        # -----------------------
        # Run strategy
        # -----------------------
        print("[WORKER] Running strategy task...")
        try:
            StrategyClass = getattr(strategy_module, "TaskRunner")
            strategy_instance = StrategyClass()
            strategy_instance.complete_task(input_path)   # ← Run task
            output_path = strategy_instance.get_output_filepath()
        except Exception as e:
            print("[WORKER] Strategy Failed:", e)
            continue

        # -----------------------
        # Upload Result
        # -----------------------
        print("[WORKER] Uploading result...")
        upload_result(job_id, output_path)

        print(f"[WORKER] Job {job_id} completed.\n")
        time.sleep(1)


# --------------------------------------------
# Program Entry
# --------------------------------------------
if __name__ == "__main__":
    # If provided: python3 worker.py <strategy>
    strategy_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_worker(strategy_arg)
