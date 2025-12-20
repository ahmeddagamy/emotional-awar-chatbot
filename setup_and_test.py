#!/usr/bin/env python3
"""
Setup and test script for the Dental Chatbot Vision System.

This script:
1. Checks if all required packages are installed
2. Tests the microexpression detector
3. Verifies the vision server can start
"""

import sys
import subprocess
import importlib
import os

def check_package(package_name, import_name=None):
    """Check if a package is installed."""
    if import_name is None:
        import_name = package_name
    
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False

def install_package(package_name):
    """Install a package using pip."""
    print(f"Installing {package_name}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    """Main setup and test function."""
    print("=" * 60)
    print("Dental Chatbot Vision System - Setup and Test")
    print("=" * 60)
    print()
    
    # Required packages
    required_packages = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "opencv-python-headless": "cv2",
        "Pillow": "PIL",
        "numpy": "numpy",
        "mediapipe": "mediapipe",
        "python-multipart": None,  # FastAPI dependency
        "jinja2": "jinja2",
        "aiofiles": "aiofiles",
    }
    
    print("Checking required packages...")
    missing_packages = []
    
    for package, import_name in required_packages.items():
        if import_name:
            if check_package(package, import_name):
                print(f"  ✓ {package} is installed")
            else:
                print(f"  ✗ {package} is missing")
                missing_packages.append(package)
        else:
            # Just check if it's in pip list
            print(f"  ? {package} (checking...)")
    
    if missing_packages:
        print()
        print(f"Missing packages: {', '.join(missing_packages)}")
        response = input("Would you like to install them now? (y/n): ")
        if response.lower() == 'y':
            for package in missing_packages:
                if not install_package(package):
                    print(f"  ✗ Failed to install {package}")
                    return False
            print("  ✓ All packages installed successfully")
        else:
            print("Please install missing packages manually:")
            print(f"  pip install {' '.join(missing_packages)}")
            return False
    else:
        print("  ✓ All required packages are installed")
    
    print()
    print("Testing microexpression detector...")
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "facial_analysis"))
        from microexpression_detector import MicroexpressionDetector
        
        detector = MicroexpressionDetector()
        print("  ✓ MicroexpressionDetector initialized successfully")
        
        # Test with a dummy image
        import numpy as np
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(dummy_frame)
        print(f"  ✓ Detector test passed (result: {result})")
        
    except Exception as e:
        print(f"  ✗ Detector test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("Testing vision server import...")
    try:
        from vision_server import app
        print("  ✓ Vision server can be imported")
    except Exception as e:
        print(f"  ✗ Vision server import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 60)
    print("Setup and tests completed successfully!")
    print("=" * 60)
    print()
    print("To start the vision server, run:")
    print("  python run_vision_server.py")
    print()
    print("Or from the facial_analysis directory:")
    print("  python vision_server.py")
    print()
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

