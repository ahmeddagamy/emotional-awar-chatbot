# Quick Start Guide

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   
   Or use the installation script:
   - Windows: `install_dependencies.bat`
   - Linux/Mac: `bash install_dependencies.sh`

2. **Verify installation:**
   ```bash
   python setup_and_test.py
   ```

## Running the System

### Step 1: Start the Vision Server

```bash
python run_vision_server.py
```

The server will start on `http://localhost:8081`

### Step 2: Start Rasa (Optional - for full chatbot functionality)

In separate terminals:

```bash
# Terminal 1: Rasa server
cd rasa_bot/actions
rasa run --enable-api

# Terminal 2: Rasa actions
cd rasa_bot/actions
rasa run actions
```

### Step 3: Open the Web Interface

Open your browser and navigate to:
```
http://localhost:8081
```

## What You Should See

1. **Web Interface:**
   - Left panel: Camera feed with real-time detection
   - Right panel: Chat interface
   - Status badges showing gaze and expression

2. **Detection Features:**
   - **Gaze Detection:** forward, away, down, left, right, up
   - **Expression Detection:** neutral, happy, sad, fear, anger, surprise, disgust

## Testing Without Camera

You can test the API endpoints directly:

```bash
# Health check
curl http://localhost:8081/health

# Get latest signals
curl http://localhost:8081/latest-signals -H "X-Sender: test_user"
```

## Troubleshooting

### Packages Not Installing

If you get import errors:
```bash
pip install --upgrade pip
pip install -r requirements.txt --force-reinstall
```

### Camera Not Working

- Check browser permissions for camera access
- Make sure no other application is using the camera
- Try a different browser (Chrome, Firefox, Edge)

### Port Already in Use

Change the port:
```bash
python run_vision_server.py --port 8082
```

## Next Steps

- Read `README_SETUP.md` for detailed documentation
- Check `facial_analysis/microexpression_detector.py` for detection algorithms
- Review `facial_analysis/vision_server.py` for API implementation

## Support

If you encounter issues:
1. Run `python setup_and_test.py` to verify installation
2. Check server logs for error messages
3. Verify all dependencies are installed correctly

