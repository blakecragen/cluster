#!/usr/bin/env bash
set -e

MASTER_IP="$1"
TOKEN="$2"
STRATEGY="$3"   # Optional argument

if [[ -z "$MASTER_IP" || -z "$TOKEN" ]]; then
    echo "Usage: ./run.sh <MASTER_IP> <K3S_TOKEN> [STRATEGY]"
    exit 1
fi

# Set default strategy if none provided
if [[ -z "$STRATEGY" ]]; then
    STRATEGY="task_runner_default"
fi

echo ""
echo "🌐 Cross-OS Worker connecting to Master: $MASTER_IP"
echo "🔑 Token (unused for cross-OS worker, but required for UX): $TOKEN"
echo "🤖 Strategy: $STRATEGY"
echo ""

# ---------------------------
# 1. Check for Python
# ---------------------------
if ! command -v python3 &> /dev/null; then
    echo "🐍 Python3 not found — installing..."

    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt update -y
        sudo apt install -y python3 python3-pip
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        if ! command -v brew &>/dev/null; then
            echo "🍺 Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        brew install python
    else
        echo "❌ Unsupported OS. Install Python3 manually."
        exit 1
    fi
else
    echo "✔ Python3 found."
fi

# ---------------------------
# 2. Ensure pip works
# ---------------------------
if ! command -v pip3 &>/dev/null; then
    echo "📦 pip3 not found — installing..."
    python3 -m ensurepip --upgrade || true
else
    echo "✔ pip3 found."
fi

# ---------------------------
# 3. Install Python dependencies
# ---------------------------
if [[ -f "requirements.txt" ]]; then
    echo "📦 Installing Python dependencies..."
    pip3 install --upgrade pip >/dev/null
    pip3 install -r requirements.txt >/dev/null
else
    echo "⚠️ requirements.txt not found."
fi

# ---------------------------
# 4. Export worker environment
# ---------------------------
export FLASK_HOST="$MASTER_IP"
export MINIO_HOST="$MASTER_IP"
export FLASK_PORT="5100"

echo "🌍 Environment configured:"
echo "   FLASK_HOST=$FLASK_HOST"
echo "   MINIO_HOST=$MINIO_HOST"
echo "   STRATEGY=$STRATEGY"

# ---------------------------
# 5. Start the worker
# ---------------------------
echo ""
echo "🚀 Starting Cross-OS Worker with strategy '$STRATEGY'..."
echo ""

python3 worker.py "$STRATEGY"
