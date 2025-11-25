#!/usr/bin/env bash
# =====================================================
# Pi Cluster Master Node - Universal Setup & Launch Script
# =====================================================
set -e

echo "🚀 Starting Pi Cluster Master Node Setup..."

# Detect OS
OS=$(uname -s)
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

# -----------------------------------------------------
# 1. Install Docker (if missing)
# -----------------------------------------------------
if ! command -v docker &> /dev/null; then
    echo "🐳 Installing Docker..."
    if [[ "$OS" == "Linux" ]]; then
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
    elif [[ "$OS" == "Darwin" ]]; then
        echo "Please install Docker Desktop manually on macOS (https://www.docker.com/products/docker-desktop)"
    fi
else
    echo "✅ Docker already installed."
fi

# -----------------------------------------------------
# 2. Install Redis (for local use / backup)
# -----------------------------------------------------
if [[ "$OS" == "Linux" ]]; then
    if ! systemctl is-active --quiet redis-server 2>/dev/null; then
        echo "Installing Redis..."
        sudo apt update -y && sudo apt install -y redis-server
        sudo systemctl enable redis-server
        sudo systemctl start redis-server
    else
        echo "✅ Redis already running."
    fi
else
    echo "Skipping Redis install on macOS (handled by Docker)."
fi

# -----------------------------------------------------
# 3. Install Python deps if needed
# -----------------------------------------------------
if ! command -v python3 &> /dev/null; then
    echo "Installing Python3..."
    if [[ "$OS" == "Linux" ]]; then
        sudo apt install -y python3 python3-pip
    else
        brew install python
    fi
fi

echo "📦 Installing Python dependencies..."
if [ -f requirements.txt ]; then
    pip3 install -r requirements.txt --break-system-packages || pip3 install -r requirements.txt
else
    echo "⚠️ No requirements.txt found, skipping Python install."
fi

# -----------------------------------------------------
# 4. Setup MinIO (if not running)
# -----------------------------------------------------
if ! docker ps --format '{{.Names}}' | grep -q cluster_minio; then
    echo "🗄️  Starting MinIO..."
    docker run -d --name cluster_minio \
        -p 9000:9000 -p 9001:9001 \
        -e "MINIO_ROOT_USER=admin" \
        -e "MINIO_ROOT_PASSWORD=admin123" \
        -v "$(pwd)/data/minio:/data" \
        quay.io/minio/minio server /data --console-address ":9001"
else
    echo "✅ MinIO already running."
fi

# -----------------------------------------------------
# 5. Stop old containers and start Docker Compose
# -----------------------------------------------------
echo "🧹 Cleaning up old containers..."
docker compose down --remove-orphans || true

echo "🏗️  Building and starting master node..."
docker compose up -d --build

echo "📦 Containers currently running:"
docker ps --filter "name=cluster_"

# -----------------------------------------------------
# 6. Print connection info
# -----------------------------------------------------
echo ""
echo "✅ Master Node is ready!"
echo "🌐 Dashboard: http://$IP:5100"
echo "🗄️  MinIO Console: http://$IP:9001"
echo "💾 Redis: $IP:6379"
echo ""
echo "Use: docker logs -f cluster_flask  to view live Flask logs"
echo ""
echo "If on Tailscale, access using your Tailscale IP:  http://$(tailscale ip -4 2>/dev/null || echo $IP):5100"
