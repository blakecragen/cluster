FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .
COPY task_config.json .
COPY task_runner_default.py .
COPY task_runner_alt.py .

CMD ["python3", "worker.py"]
