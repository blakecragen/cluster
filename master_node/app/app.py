#!/usr/bin/env python3
"""
Pi Cluster Master Node
Flask REST API + Dashboard for task upload, queueing, result handling, and monitoring
"""

from flask import Flask, request, jsonify, render_template, Response
import redis, boto3, os, uuid, datetime, socket, json
import subprocess

app = Flask(__name__)

# --- Redis setup ---
r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"),
                port=6379,
                decode_responses=True)

# --- MinIO setup ---
s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{os.getenv('MINIO_HOST', 'localhost')}:9000",
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
)

INPUT_BUCKET = "inputs"
RESULT_BUCKET = "results"

# Ensure buckets exist
for b in [INPUT_BUCKET, RESULT_BUCKET]:
    try:
        s3.create_bucket(Bucket=b)
    except Exception:
        pass


# ---------- HELPERS ----------

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calc_elapsed(start, end):
    t1 = datetime.datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    t2 = datetime.datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
    return (t2 - t1).total_seconds()


def load_k3s_join_info():
    """
    Loads master_ip + token from /tmp/k3s_join_info.json.
    """
    try:
        with open("/tmp/k3s_join_info.json", "r") as f:
            data = json.load(f)
            return (
                data.get("master_ip", "unknown"),
                data.get("token", "K3S_NOT_RUNNING"),
            )
    except:
        return "unknown", "K3S_NOT_RUNNING"


def get_master_ip():
    """
    Returns best master IP:
    1. Tailscale IP passed via docker env
    2. LAN IP fallback
    3. Unknown fallback
    """
    # 1. Tailscale IP passed in from run.sh
    ts_env = os.getenv("TS_IP")
    if ts_env and len(ts_env.strip()) > 0:
        return ts_env.strip()

    # 2. LAN IP fallback
    try:
        hostname = socket.gethostname()
        lan_ip = socket.gethostbyname(hostname)
        if lan_ip and not lan_ip.startswith("127."):
            return lan_ip
    except:
        pass

    return "UNKNOWN"

# ---------- ROUTES ----------

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    priority = request.form.get("priority", "1")
    if priority not in ["0", "1", "2"]:
        return jsonify({"error": "Priority must be 0, 1, or 2"}), 400

    timestamp = now_str()
    job_id = str(uuid.uuid4())
    ext = os.path.splitext(f.filename)[1] or ".zip"
    filename = f"{os.path.splitext(f.filename)[0]}_{timestamp.replace(':','-').replace(' ','_')}{ext}"

    s3.upload_fileobj(f, INPUT_BUCKET, filename)

    job_data = {
        "id": job_id,
        "filename": filename,
        "priority": priority,
        "status": "queued",
        "timestamp_queued": timestamp,
        "timestamp_claimed": "",
        "timestamp_completed": "",
        "claimed_by": "",
        "elapsed_seconds": "",
        "result_filename": "",
        "collected": "False"
    }

    r.hset(job_id, mapping=job_data)
    r.rpush(f"job_queue_prio{priority}", job_id)
    return jsonify(job_data), 201


@app.route("/claim_job", methods=["POST"])
def claim_job():
    worker_ip = request.remote_addr

    # Pop highest priority job
    job_id = None
    for p in ["0", "1", "2"]:
        job_id = r.lpop(f"job_queue_prio{p}")
        if job_id:
            break

    if not job_id:
        return jsonify({"message": "No jobs in any queue"}), 200

    job = r.hgetall(job_id)
    job["status"] = "claimed"
    job["timestamp_claimed"] = now_str()
    job["claimed_by"] = worker_ip

    r.hset(job_id, mapping=job)
    return jsonify(job)


@app.route("/upload_result/<job_id>", methods=["POST"])
def upload_result(job_id):
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    job = r.hgetall(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    f = request.files["file"]
    ext = os.path.splitext(f.filename)[1] or ".bin"
    result_name = f"result_{now_str().replace(':','-').replace(' ','_')}{ext}"

    s3.upload_fileobj(f, RESULT_BUCKET, result_name)

    job["result_filename"] = result_name
    job["status"] = "completed"
    job["timestamp_completed"] = now_str()
    job["collected"] = "False"

    if job.get("timestamp_claimed"):
        job["elapsed_seconds"] = str(
            round(calc_elapsed(job["timestamp_claimed"], job["timestamp_completed"]), 2)
        )

    r.hset(job_id, mapping=job)
    return jsonify({"message": f"Result uploaded for {job_id}",
                    "result_filename": result_name}), 200


@app.route("/download_result/<job_id>", methods=["GET"])
def download_result(job_id):
    job = r.hgetall(job_id)
    if not job or not job.get("result_filename"):
        return jsonify({"error": "Result not found"}), 404

    result_obj = s3.get_object(Bucket=RESULT_BUCKET, Key=job["result_filename"])
    data = result_obj["Body"].read()

    job["collected"] = "True"
    r.hset(job_id, mapping=job)

    mime = "application/octet-stream"
    if job["result_filename"].endswith(".txt"):
        mime = "text/plain"
    elif job["result_filename"].endswith(".csv"):
        mime = "text/csv"
    elif job["result_filename"].endswith(".zip"):
        mime = "application/zip"

    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = f"attachment; filename={job['result_filename']}"
    return response


@app.route("/mark_collected/<job_id>", methods=["POST"])
def mark_collected(job_id):
    job = r.hgetall(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.get("status") != "completed":
        return jsonify({"error": "Job not completed yet"}), 400

    job["collected"] = "True"
    r.hset(job_id, mapping=job)
    return jsonify({"message": f"Job {job_id} marked as collected."}), 200


@app.route("/delete_job/<job_id>", methods=["POST"])
def delete_job(job_id):
    job = r.hgetall(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Remove from queues
    for p in ["0", "1", "2"]:
        r.lrem(f"job_queue_prio{p}", 0, job_id)

    # Delete Redis record
    r.delete(job_id)

    # Delete MinIO files
    try:
        if job.get("filename"):
            s3.delete_object(Bucket=INPUT_BUCKET, Key=job["filename"])
        if job.get("result_filename"):
            s3.delete_object(Bucket=RESULT_BUCKET, Key=job["result_filename"])
    except Exception as e:
        print(f"[WARN] MinIO delete failed: {e}")

    return jsonify({"message": f"Job {job_id} deleted."}), 200


@app.route("/")
def dashboard():
    """
    Render dashboard:
    - Shows jobs
    - Shows master IP (Tailscale preferred)
    - Shows join token
    """
    all_jobs = []
    for k in r.keys("*"):
        if r.type(k) == "hash":
            all_jobs.append(r.hgetall(k))

    # Elapsed calculation
    for job in all_jobs:
        if job.get("timestamp_claimed") and not job.get("timestamp_completed"):
            job["elapsed_seconds"] = round(
                calc_elapsed(job["timestamp_claimed"], now_str()), 2
            )
        elif job.get("timestamp_claimed") and job.get("timestamp_completed"):
            job["elapsed_seconds"] = round(
                calc_elapsed(job["timestamp_claimed"], job["timestamp_completed"]), 2
            )
        else:
            job["elapsed_seconds"] = ""

    all_jobs.sort(key=lambda x: (int(x.get("priority", 3)),
                                 x.get("timestamp_queued", "")))

    # Load token from K3s installer JSON
    k3s_ip, join_token = load_k3s_join_info()

    # Replace IP with Tailscale / LAN if available
    master_ip = get_master_ip()
    print(f"[INFO] Dashboard using master IP: {master_ip}")

    return render_template(
        "dashboard.html",
        jobs=all_jobs,
        server_name=socket.gethostname(),
        time=now_str(),
        master_ip=master_ip,
        join_token=join_token,
    )


@app.route("/purge_all", methods=["POST"])
def purge_all():
    deleted_jobs = 0
    deleted_files = 0

    for key in r.scan_iter("*"):
        r.delete(key)
        deleted_jobs += 1

    for p in ["0", "1", "2"]:
        r.delete(f"job_queue_prio{p}")

    for bucket in [INPUT_BUCKET, RESULT_BUCKET]:
        objs = s3.list_objects_v2(Bucket=bucket)
        if "Contents" in objs:
            for obj in objs["Contents"]:
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
                deleted_files += 1

    return jsonify({
        "message": "All Redis jobs and MinIO files purged.",
        "jobs_deleted": deleted_jobs,
        "files_deleted": deleted_files
    }), 200


@app.route("/nodes", methods=["GET"])
def list_nodes():
    """
    Returns Kubernetes node information for the Dashboard.
    """
    try:
        output = subprocess.check_output(
            ["kubectl", "get", "nodes", "-o", "json"],
            text=True
        )
        data = json.loads(output)

        nodes = []
        for item in data["items"]:
            status = "Unknown"
            for cond in item["status"]["conditions"]:
                if cond["type"] == "Ready":
                    status = "Ready" if cond["status"] == "True" else "NotReady"

            addresses = {a["type"]: a["address"]
                         for a in item["status"]["addresses"]}

            nodes.append({
                "name": item["metadata"]["name"],
                "status": status,
                "role": item["metadata"]
                         .get("labels", {}).get("kubernetes.io/role", "worker"),
                "arch": item["status"]["nodeInfo"]["architecture"],
                "os_image": item["status"]["nodeInfo"]["osImage"],
                "kernel": item["status"]["nodeInfo"]["kernelVersion"],
                "cpu": item["status"]["capacity"].get("cpu", "N/A"),
                "internal_ip": addresses.get("InternalIP", "N/A"),
                "heartbeat": item["status"]["conditions"][-1]["lastHeartbeatTime"]
            })

        return jsonify(nodes)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/register_worker", methods=["POST"])
def register_worker():
    data = request.json
    worker_id = data.get("worker_id")
    if not worker_id:
        return jsonify({"error": "Missing worker_id"}), 400

    r.hset(f"worker:{worker_id}", mapping={
        "worker_id": worker_id,
        "hostname": data.get("hostname", ""),
        "ip": data.get("ip", request.remote_addr),
        "os": data.get("os", "unknown"),
        "cpu": data.get("cpu", "unknown"),
        "kernel": data.get("kernel", "unknown"),
        "task_runner": data.get("task_runner", "default"),
        "last_heartbeat": datetime.datetime.now().isoformat(),
        "status": "online"
    })

    return jsonify({"message": "worker registered"}), 200


@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json
    worker_id = data.get("worker_id")

    if not worker_id:
        return jsonify({"error": "Missing worker_id"}), 400

    # If the worker didn't send a timestamp, generate a UTC one
    timestamp = data.get("last_heartbeat",
                         datetime.datetime.now(datetime.timezone.utc).isoformat())

    if not r.exists(f"worker:{worker_id}"):
        return jsonify({"error": "Worker not registered"}), 404

    r.hset(f"worker:{worker_id}", "last_heartbeat", timestamp)
    r.hset(f"worker:{worker_id}", "status", "online")

    return jsonify({"message": "heartbeat ok"}), 200



@app.route("/workers")
def get_workers():
    """
    Return ONLY active workers (heartbeat within 20 seconds).
    Remove stale ones automatically.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = 20   # seconds

    worker_keys = r.keys("worker:*")
    active_workers = []

    for key in worker_keys:
        w = r.hgetall(key)
        if not w:
            r.delete(key)
            continue

        try:
            last = datetime.datetime.fromisoformat(w["last_heartbeat"])
        except Exception:
            r.delete(key)
            continue

        elapsed = (now - last).total_seconds()

        if elapsed > cutoff:
            # Worker is stale — delete it
            print(f"[WORKERS] Removing stale worker {w.get('worker_id')} ({elapsed:.1f}s old)")
            r.delete(key)
            continue

        active_workers.append(w)

    return jsonify(active_workers)


# ---------- STARTUP RECOVERY ----------
def repopulate_queues():
    all_jobs = [r.hgetall(k) for k in r.keys("*") if r.type(k) == "hash"]
    restored = 0
    for job in all_jobs:
        if job.get("status") == "queued":
            qname = f"job_queue_prio{job.get('priority', '1')}"
            if job["id"] not in r.lrange(qname, 0, -1):
                r.rpush(qname, job["id"])
                restored += 1
    if restored:
        print(f"[INIT] Restored {restored} queued job(s).")

def prune_dead_workers(timeout=10):
    now = datetime.datetime.now()
    worker_keys = r.keys("worker:*")

    for key in worker_keys:
        w = r.hgetall(key)
        if not w:
            r.delete(key)
            continue

        last = datetime.datetime.fromisoformat(w.get("last_heartbeat"))
        elapsed = (now - last).total_seconds()

        if elapsed > timeout:
            print(f"[PRUNE] Worker {w.get('worker_id')} expired ({elapsed}s). Removing.")
            r.delete(key)



def clear_all_workers():
    worker_keys = r.keys("worker:*")
    for key in worker_keys:
        r.delete(key)
    print(f"[INIT] Cleared {len(worker_keys)} workers on startup.")



# ---------- MAIN ----------
if __name__ == "__main__":
    print("[INFO] Purging stale workers at startup...")
    prune_dead_workers(timeout=0)   # Immediately delete all workers

    repopulate_queues()
    print("[INFO] Pi Cluster Master API running...")

    # Background prune thread
    import threading, time
    def prune_loop():
        while True:
            prune_dead_workers(timeout=10)
            time.sleep(5)

    threading.Thread(target=prune_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=5100)

