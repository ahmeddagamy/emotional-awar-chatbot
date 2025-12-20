#!/bin/bash
# Production startup script for Dental Chatbot

set -e

echo "=========================================="
echo "Dental Chatbot - Production Startup"
echo "=========================================="

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo "✓ Loaded environment variables from .env"
else
    echo "⚠ Warning: .env file not found. Using defaults."
fi

# Set environment to production
export ENV=production

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate
echo "✓ Virtual environment activated"

# Install/update dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Dependencies installed"

# Start Vision Server in background
echo "Starting Vision API Server..."
python run_vision_server.py --host ${VISION_API_HOST:-0.0.0.0} --port ${VISION_API_PORT:-8081} &
VISION_PID=$!
echo "✓ Vision Server started (PID: $VISION_PID)"
echo "  Access at: http://localhost:${VISION_API_PORT:-8081}"

# Wait a moment for vision server to start
sleep 2

# Start Rasa Server (if needed)
if [ "$START_RASA" != "false" ]; then
    echo "Starting Rasa Server..."
    cd rasa_bot/actions
    rasa run --enable-api --port ${RASA_PORT:-5005} &
    RASA_PID=$!
    echo "✓ Rasa Server started (PID: $RASA_PID)"
    cd ../..
    
    sleep 2
    
    echo "Starting Rasa Actions Server..."
    cd rasa_bot/actions
    rasa run actions --port ${RASA_ACTIONS_PORT:-5055} &
    ACTIONS_PID=$!
    echo "✓ Rasa Actions Server started (PID: $ACTIONS_PID)"
    cd ../..
fi

echo ""
echo "=========================================="
echo "All services started successfully!"
echo "=========================================="
echo "Vision API: http://localhost:${VISION_API_PORT:-8081}"
if [ "$START_RASA" != "false" ]; then
    echo "Rasa API: http://localhost:${RASA_PORT:-5005}"
    echo "Rasa Actions: http://localhost:${RASA_ACTIONS_PORT:-5055}"
fi
echo ""
echo "Press Ctrl+C to stop all services"
echo "=========================================="

# Wait for all background processes
wait

