#!/bin/bash
# Start script for Kaderblick Camera API

echo "Starting Kaderblick Camera API..."
echo "======================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if requirements are installed
echo "Checking dependencies..."
python3 -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Create captured_images directory if it doesn't exist
mkdir -p captured_images

# Start the application
echo ""
echo "Starting server on http://0.0.0.0:5000"
echo "Press Ctrl+C to stop"
echo ""

python3 app.py
