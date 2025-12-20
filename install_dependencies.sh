#!/bin/bash
# Installation script for Dental Chatbot Vision System (Linux/Mac)

echo "========================================"
echo "Installing Dependencies"
echo "========================================"
echo ""

python3 -m pip install --upgrade pip

echo ""
echo "Installing core dependencies..."
python3 -m pip install -r requirements.txt

echo ""
echo "========================================"
echo "Installation Complete!"
echo "========================================"
echo ""
echo "To verify installation, run:"
echo "  python3 setup_and_test.py"
echo ""
echo "To start the vision server, run:"
echo "  python3 run_vision_server.py"
echo ""

