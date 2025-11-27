#!/usr/bin/env bash
# =====================================================
# Pi Cluster Master Node - Universal Setup & Launch Script
# =====================================================
set -e

echo "🚀 Starting Pi Cluster Master Node Setup..."

OS=$(uname -s)

##############################################
# PART 0 — GET HOST TAILSCALE IP
##############################################

get_tailscale_ip() {
    if command -v tailscale >/dev/null 2>&1; then
        # strip warnings, return last line only
        ts=$(tailscale ip -4 2>/dev/null | tail -n1)
        echo "$ts"
    fi
}

TS_IP=$(get_tailscale_ip)
echo "🌐 Tailscale IP detected: ${TS_IP:-none}"

##############################################
# PART A — DOCKER STACK (Flask/Redis/MinIO)
##############################################

echo "=== 🐳 Setting up Docker Stack ==="

# Ensure docker compose exists
if command -v docker compose &>/dev/null; then
    COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE="docker-compose"
else
    echo "⚠️ Docker Compose missing — install Docker Desktop or docker-compose."
    exit 1
fi

# Ensure Docker exists
if ! command -v docker &>/dev/null; then
    echo "🐳 Installing Docker..."
    if [[ "$OS" == "Linux" ]]; then
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
    else
        echo "Install Docker Desktop on macOS."
        exit 1
    fi
else
    echo "✔ Docker installed"
fi

# Cleanup conflicting containers
echo "🧹 Cleaning old containers..."
for c in cluster_minio cluster_redis cluster_flask minio redis; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${c}$"; then
        docker stop "$c" >/dev/null 2>&1 || true
        docker rm -f "$c" >/dev/null 2>&1 || true
    fi
done

# Remove dangling resources
docker network prune -f >/dev/null 2>&1 || true
docker volume prune -f >/dev/null 2>&1 || true

# Start Docker Compose WITH TS_IP ENV
echo "🏗️  Starting Docker Compose stack..."
TS_IP="$TS_IP" $COMPOSE down --remove-orphans || true
TS_IP="$TS_IP" $COMPOSE up -d --build

##############################################
# PART B — K3s MASTER SETUP (macOS + Linux)
##############################################

echo ""
echo "=== ☸️  Setting up K3s Kubernetes Master ==="

if [[ "$OS" == "Darwin" ]]; then
    # macOS → Use Multipass VM
    if ! command -v multipass >/dev/null; then
        echo "❌ Multipass required: brew install --cask multipass"
        exit 1
    fi

    if ! multipass info master >/dev/null 2>&1; then
        echo "📦 Creating Multipass VM..."
        multipass launch --name master --mem 4G --disk 20G
    else
        echo "✔ Multipass VM exists"
    fi

    MASTER_IP=$(multipass info master | grep IPv4 | awk '{print $2}')
    echo "🌐 Master VM IP: $MASTER_IP"

    multipass exec master -- bash -c "
        if ! command -v k3s >/dev/null; then
            echo 'Installing K3s...'
            curl -sfL https://get.k3s.io | sh -
        else
            echo '✔ K3s installed'
        fi
    "

    KUBECTL="multipass exec master -- sudo kubectl"

else
    # Linux/Pi
    MASTER_IP=$(hostname -I | awk '{print $1}')
    if ! command -v k3s >/dev/null; then
        echo "Installing K3s..."
        curl -sfL https://get.k3s.io | sh -
    else
        echo "✔ K3s installed"
    fi

    KUBECTL="sudo kubectl"
fi

##############################################
# Extract join token & save for dashboard
##############################################

echo ""
echo "🔑 Getting K3s join token..."

if [[ "$OS" == "Darwin" ]]; then
    TOKEN=$(multipass exec master -- sudo cat /var/lib/rancher/k3s/server/node-token)
else
    TOKEN=$(sudo cat /var/lib/rancher/k3s/server/node-token)
fi

echo "✔ Token retrieved"

# Store for Flask dashboard
echo "{\"master_ip\": \"$MASTER_IP\", \"token\": \"$TOKEN\", \"tailscale_ip\": \"$TS_IP\"}" \
    > /tmp/k3s_join_info.json

##############################################
# Final Output
##############################################

echo ""
echo "🎉 Master Node Ready!"

PUBLIC_IP="${TS_IP:-$MASTER_IP}"

echo "Dashboard:    http://$PUBLIC_IP:5100"
echo "MinIO:        http://$PUBLIC_IP:9001"
echo "Redis:        $PUBLIC_IP:6379"
echo "K3s API:      https://$MASTER_IP:6443"
echo ""
echo "Worker join command:"
echo "curl -sfL https://get.k3s.io | K3S_URL=\"https://$PUBLIC_IP:6443\" K3S_TOKEN=\"$TOKEN\" sh -"
echo ""
echo "Data saved for dashboard: /tmp/k3s_join_info.json"
