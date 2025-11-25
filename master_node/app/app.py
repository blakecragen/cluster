#!/usr/bin/env python3
"""
Pi Cluster Master Node
Flask REST API + Dashboard for task upload, queueing, result handling, and monitoring
"""

from flask import Flask, request, jsonify, render_template, Response
import redis, boto3, os, uuid, datetime, socket

app = Flask(__name__)

# --- Redis setup ---
r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, decode_responses=True)

# --- MinIO setup ---
s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{os.getenv('MINIO_HOST', 'localhost')}:9000",
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
)

INPUT_BUCKET = "inputs"
RESULT_BUCKET = "results"

# Ensure both buckets exist
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
    """Worker uploads result file for a completed job."""
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
    return jsonify({"message": f"Result uploaded for {job_id}", "result_filename": result_name}), 200


@app.route("/download_result/<job_id>", methods=["GET"])
def download_result(job_id):
    """Stream the result file from MinIO and mark as collected."""
    job = r.hgetall(job_id)
    if not job or not job.get("result_filename"):
        return jsonify({"error": "Result not found"}), 404

    result_obj = s3.get_object(Bucket=RESULT_BUCKET, Key=job["result_filename"])
    data = result_obj["Body"].read()

    job["collected"] = "True"
    r.hset(job_id, mapping=job)

    # MIME type detection
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
    for p in ["0", "1", "2"]:
        r.lrem(f"job_queue_prio{p}", 0, job_id)
    r.delete(job_id)
    try:
        if "filename" in job:
            s3.delete_object(Bucket=INPUT_BUCKET, Key=job["filename"])
        if "result_filename" in job:
            s3.delete_object(Bucket=RESULT_BUCKET, Key=job["result_filename"])
    except Exception as e:
        print(f"[WARN] Failed to delete {job.get('filename')}: {e}")
    return jsonify({"message": f"Job {job_id} deleted."}), 200


@app.route("/queue")
def queue_list():
    queues = {}
    for p in ["0", "1", "2"]:
        ids = r.lrange(f"job_queue_prio{p}", 0, -1)
        queues[f"prio{p}"] = [r.hgetall(i) for i in ids]
    return jsonify(queues)


@app.route("/claimed_jobs", methods=["GET"])
def claimed_jobs():
    results = []
    for key in r.scan_iter("*"):
        if r.type(key) != "hash":
            continue
        job = r.hgetall(key)
        if not job or "id" not in job:
            continue
        if job.get("status") in ["claimed", "completed"]:
            entry = {
                "job_id": job.get("id"),
                "filename": job.get("filename"),
                "result_filename": job.get("result_filename"),
                "priority": job.get("priority", "N/A"),
                "status": job.get("status"),
                "claimed_by": job.get("claimed_by"),
                "timestamp_claimed": job.get("timestamp_claimed"),
                "timestamp_completed": job.get("timestamp_completed"),
                "collected": job.get("collected"),
            }
            results.append(entry)
    results.sort(key=lambda x: int(x.get("priority", 3)))
    return jsonify(results)


@app.route("/healthz")
def healthz():
    try:
        redis_ok = r.ping()
        buckets = s3.list_buckets()
        return jsonify({
            "server": socket.gethostname(),
            "redis": redis_ok,
            "minio": True if buckets else False,
            "time": now_str()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def dashboard():
    all_jobs = [r.hgetall(k) for k in r.keys("*") if r.type(k) == "hash"]
    for job in all_jobs:
        if job.get("timestamp_claimed") and not job.get("timestamp_completed"):
            end_time = now_str()
            job["elapsed_seconds"] = round(calc_elapsed(job["timestamp_claimed"], end_time), 2)
        elif job.get("timestamp_claimed") and job.get("timestamp_completed"):
            job["elapsed_seconds"] = round(calc_elapsed(job["timestamp_claimed"], job["timestamp_completed"]), 2)
        else:
            job["elapsed_seconds"] = ""
    all_jobs.sort(key=lambda x: (int(x.get("priority", 3)), x.get("timestamp_queued", "")))
    return render_template("dashboard.html",
                           jobs=all_jobs,
                           server_name=socket.gethostname(),
                           time=now_str())


@app.route("/purge_all", methods=["POST"])
def purge_all():
    """⚠️ Delete ALL jobs and ALL files from Redis and MinIO."""
    deleted_jobs = 0
    deleted_files = 0

    for key in r.scan_iter("*"):
        r.delete(key)
        deleted_jobs += 1
    for p in ["0", "1", "2"]:
        r.delete(f"job_queue_prio{p}")

    for bucket in [INPUT_BUCKET, RESULT_BUCKET]:
        try:
            objs = s3.list_objects_v2(Bucket=bucket)
            if "Contents" in objs:
                for obj in objs["Contents"]:
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    deleted_files += 1
        except Exception as e:
            print(f"[WARN] Failed to purge bucket {bucket}: {e}")

    print(f"[PURGE] Removed {deleted_jobs} jobs and {deleted_files} files.")
    return jsonify({
        "message": "All Redis jobs and MinIO files purged.",
        "jobs_deleted": deleted_jobs,
        "files_deleted": deleted_files
    }), 200


# ---------- STARTUP RECOVERY ----------
def repopulate_queues():
    all_jobs = [r.hgetall(k) for k in r.keys("*") if r.type(k) == "hash"]
    restored = 0
    for job in all_jobs:
        if job and job.get("status") == "queued":
            qname = f"job_queue_prio{job.get('priority', '1')}"
            if job["id"] not in r.lrange(qname, 0, -1):
                r.rpush(qname, job["id"])
                restored += 1
    if restored:
        print(f"[INIT] Restored {restored} queued job(s) from Redis on startup.")


if __name__ == "__main__":
    repopulate_queues()
    print("[INFO] Pi Cluster Master API running...")
    app.run(host="0.0.0.0", port=5000)
