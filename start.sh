#!/bin/bash
set -e

# NyayaVoice Startup Script
# This script sets up and starts the NyayaVoice legal aid assistant

echo "🚀 Starting NyayaVoice Legal Aid Assistant..."
echo "=================================================="
echo "Current directory: $(pwd)"
echo "Python version: $(python3 --version 2>/dev/null || echo 'Python not found')"
echo "Node.js version: $(node --version 2>/dev/null || echo 'Node.js not found')"
echo "PORT is set to: ${PORT:-8080}"
echo ""

# Check if virtual environment exists and activate it
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "📦 Activating virtual environment (.venv)..."
    source .venv/bin/activate
else
    echo "⚠️  No virtual environment found. Installing dependencies globally..."
fi

# Install/update Python dependencies
echo "📦 Installing Python dependencies..."
pip install --quiet -r requirements.txt

# Check if Qdrant is running (optional)
echo "🔍 Checking Qdrant connection..."
python3 -c "
import os
from qdrant_client import QdrantClient
try:
    qdrant_url = os.getenv('QDRANT_URL', ':memory:')
    if qdrant_url != ':memory:':
        client = QdrantClient(url=qdrant_url, api_key=os.getenv('QDRANT_API_KEY'))
        client.get_collections()
        print('✅ Qdrant connection successful')
    else:
        print('ℹ️  Using in-memory Qdrant')
except Exception as e:
    echo '⚠️  Qdrant connection failed, will use in-memory storage'
"

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p generated_docs logs

# Set environment variables
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export BACKEND_URL="${BACKEND_URL:-http://localhost:${PORT:-8080}}"

echo ""
echo "🌟 Starting uvicorn server..."
echo "📡 Server will be available at: http://0.0.0.0:${PORT:-8080}"
echo "📚 API documentation at: http://localhost:${PORT:-8080}/docs"
echo "🔄 Press Ctrl+C to stop the server"
echo ""

# Start the server with proper logging
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8080} \
    --workers 1 \
    --log-level info \
    --access-log \
    --reload \
    --reload-dir . \
    --reload-dir backend \
    --reload-dir frontend
