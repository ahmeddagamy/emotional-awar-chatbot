#!/usr/bin/env python3
"""
Standalone script to run the Vision API server.

Usage:
    python run_vision_server.py [--port PORT] [--host HOST]
"""

import os
import sys
import argparse

# Add facial_analysis to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "facial_analysis"))

from vision_server import app
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Vision API server")
    parser.add_argument("--port", type=int, default=8081, help="Port to run the server on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    args = parser.parse_args()
    
    print(f"Starting Vision API server on {args.host}:{args.port}")
    print(f"Access the web interface at: http://localhost:{args.port}")
    print(f"Health check: http://localhost:{args.port}/health")
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        reload=args.reload
    )

