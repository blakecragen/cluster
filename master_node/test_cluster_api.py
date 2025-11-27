#!/usr/bin/env python3
"""
test_cluster_api.py
Simulates full Pi Cluster workflow: upload → claim → process → upload result → collect → verify.
"""

import requests
import time
from pprint import pprint
from pathlib import Path

# ======== CONFIG ========
MASTER_IP = "localhost"    # or your Pi’s IP (LAN or Tailscale)
PORT = 5100
BASE_URL = f"http://{MASTER_IP}:{PORT}"

# ======== HELPERS ========

def safe_json(resp):
    """Try to return JSON, otherwise print raw text."""
    try:
        data = resp.json()
        return data
    except Exception:
        print(f"[WARN] Non-JSON response ({resp.status_code}): {resp.text}")
        return {}

def upload_job(filepath, priority="1"):
    print(f"\n[UPLOAD] Uploading {filepath} (priority={priority}) ...")
    with open(filepath, "rb") as f:
        files = {"file": f}
        data = {"priority": priority}
        resp = requests.post(f"{BASE_URL}/upload", files=files, data=data)
    result = safe_json(resp)
    pprint(result)
    return result.get("id")

def check_queue():
    print("\n[QUEUE] Current queue:")
    resp = requests.get(f"{BASE_URL}/queue")
    pprint(safe_json(resp))

def claim_job():
    print("\n[CLAIM] Worker claiming next job...")
    resp = requests.post(f"{BASE_URL}/claim_job")
    result = safe_json(resp)
    pprint(result)
    return result.get("id")

def complete_job(job_id):
    print(f"\n[COMPLETE] Marking {job_id} as completed...")
    data = {"status": "completed"}
    resp = requests.post(f"{BASE_URL}/update_status/{job_id}", json=data)
    pprint(safe_json(resp))

def upload_result(job_id, result_path):
    print(f"\n[RESULT UPLOAD] Uploading result for job {job_id} ...")
    with open(result_path, "rb") as f:
        files = {"file": f}
        resp = requests.post(f"{BASE_URL}/upload_result/{job_id}", files=files)
    print(f"[DEBUG] HTTP {resp.status_code}")
    result = safe_json(resp)
    pprint(result)

def mark_collected(job_id):
    print(f"\n[MARK COLLECTED] Marking job {job_id} as collected ...")
    resp = requests.post(f"{BASE_URL}/mark_collected/{job_id}")
    pprint(safe_json(resp))

def cleanup_completed():
    print("\n[CLEANUP] Removing collected completed jobs ...")
    resp = requests.post(f"{BASE_URL}/cleanup_completed")
    pprint(safe_json(resp))

def claimed_jobs():
    print("\n[CLAIMED JOBS] Current claimed/completed jobs:")
    resp = requests.get(f"{BASE_URL}/claimed_jobs")
    pprint(safe_json(resp))

def health_check():
    print("\n[HEALTHZ] Checking cluster health...")
    resp = requests.get(f"{BASE_URL}/healthz")
    pprint(safe_json(resp))


# ======== MAIN TEST SEQUENCE ========
if __name__ == "__main__":
    print("=== Pi Cluster API Test Script ===")

    # Create dummy files
    Path("test.zip").write_text("Pretend this is a job input file.")
    Path("result.txt").write_text("Complete!")

    # Step 1: Check cluster health
    health_check()

    # Step 2: Upload test jobs (1 per priority level)
    job_ids = []
    for prio in ["0", "1", "2"]:
        job_id = upload_job("test.zip", priority=prio)
        if job_id:
            job_ids.append(job_id)
        time.sleep(0.5)

    # Step 3: View the queue
    # check_queue()

    # Step 4: Simulate a worker claiming & uploading a result
    # claimed_id = claim_job()
    # time.sleep(2)
    # if claimed_id:
    #     upload_result(claimed_id, "result.txt")
    #     # mark_collected(claimed_id)
    # else:
    #     print("[WARN] No job was claimed; skipping result upload.")

    # Step 5: View claimed/completed jobs
    # claimed_jobs()

    # Step 6: Optional cleanup (disabled for debugging)
    # cleanup_completed()

    print("\n✅ Test sequence complete.")
