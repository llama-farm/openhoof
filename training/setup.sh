#!/bin/bash
# Setup training environment for OpenHoof tool router
# Auto-detects Mac vs Linux and installs the right deps

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/../.venv-train"

echo "🦙 OpenHoof Training Setup"
echo ""

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# Detect platform
if [[ "$(uname)" == "Darwin" ]]; then
    echo "🍎 Detected macOS — installing unsloth-mlx (Apple Silicon)"
    pip install -r "$SCRIPT_DIR/requirements-mac.txt"
    echo ""
    echo "✅ Ready! Run:"
    echo "   source .venv-train/bin/activate"
    echo "   python training/train_tool_router.py"
else
    echo "🐧 Detected Linux — installing unsloth (CUDA)"
    # Check for CUDA
    if command -v nvidia-smi &> /dev/null; then
        echo "   CUDA detected: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
    else
        echo "   ⚠️  No CUDA detected. Training will be slow on CPU."
    fi
    pip install -r "$SCRIPT_DIR/requirements-linux.txt"
    echo ""
    echo "✅ Ready! Run:"
    echo "   source .venv-train/bin/activate"
    echo "   python training/train_tool_router.py --backend cuda"
fi

echo ""
echo "Pipeline commands:"
echo "   python training/pipeline.py status    # Check data & model status"
echo "   python training/pipeline.py run       # Full training pipeline"
echo "   python training/pipeline.py generate  # Generate more training data"
