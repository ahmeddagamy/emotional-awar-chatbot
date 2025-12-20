# Dental Chatbot Vision System - Setup Guide

This guide will help you set up and run the dental chatbot with facial expression and gaze detection.

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Webcam (for testing the vision features)

## Installation

### 1. Install Dependencies

Install all required packages:

```bash
pip install -r requirements.txt
```

Or use the setup script:

```bash
python setup_and_test.py
```

### 2. Verify Installation

Run the setup and test script to verify everything is working:

```bash
python setup_and_test.py
```

This will:
- Check if all required packages are installed
- Test the microexpression detector
- Verify the vision server can be imported

## Running the System

### Start the Vision API Server

The vision server handles facial expression and gaze detection:

```bash
python run_vision_server.py
```

Or directly:

```bash
cd facial_analysis
python vision_server.py
```

The server will start on `http://localhost:8081` by default.

You can customize the port and host:

```bash
python run_vision_server.py --port 8081 --host 0.0.0.0
```

### Start the Rasa Chatbot

In a separate terminal, start the Rasa server:

```bash
cd rasa_bot/actions
rasa run --enable-api
```

This starts the Rasa REST API on `http://localhost:5005`.

### Start Rasa Actions Server

In another terminal, start the actions server:

```bash
cd rasa_bot/actions
rasa run actions
```

## Accessing the Web Interface

Once the vision server is running, open your browser and navigate to:

```
http://localhost:8081
```

You should see the dental chatbot interface with:
- Camera feed (left panel)
- Chat interface (right panel)
- Real-time gaze and expression detection

## API Endpoints

### Vision API (Port 8081)

- `GET /` - Web interface
- `GET /health` - Health check
- `POST /ingest-frame` - Submit a video frame for processing
- `GET /latest-signals` - Get latest gaze and expression signals
- `GET /stats` - Get server statistics

### Rasa API (Port 5005)

- `POST /webhooks/rest/webhook` - Send messages to the chatbot

## Testing

### Test the Vision Server

1. Start the vision server:
   ```bash
   python run_vision_server.py
   ```

2. Check health:
   ```bash
   curl http://localhost:8081/health
   ```

3. Open the web interface:
   ```
   http://localhost:8081
   ```

### Test the Microexpression Detector

You can test the detector directly:

```python
from facial_analysis.microexpression_detector import MicroexpressionDetector
import cv2
import numpy as np

detector = MicroexpressionDetector()

# Test with a dummy frame
frame = np.zeros((480, 640, 3), dtype=np.uint8)
result = detector.detect(frame)
print(result)
```

## Troubleshooting

### MediaPipe Installation Issues

If you encounter issues with MediaPipe on Windows:

```bash
pip install mediapipe --upgrade
```

### OpenCV Issues

If OpenCV fails to import:

```bash
pip uninstall opencv-python opencv-python-headless
pip install opencv-python-headless
```

### Port Already in Use

If port 8081 is already in use, change it:

```bash
python run_vision_server.py --port 8082
```

And update the frontend configuration in `web_integration/static/webcam.js`:

```javascript
const VISION_API_BASE = "http://localhost:8082";
```

### Camera Permission Issues

- Make sure your browser has camera permissions
- On Chrome/Edge: Check `chrome://settings/content/camera`
- On Firefox: Check `about:preferences#privacy`

## Architecture

```
┌─────────────────┐
│  Web Browser    │
│  (Frontend)     │
└────────┬────────┘
         │
         ├─── POST /ingest-frame ────┐
         │                            │
         └─── GET /latest-signals ────┤
                                       │
                              ┌────────▼────────┐
                              │  Vision Server  │
                              │  (Port 8081)    │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │ Microexpression  │
                              │    Detector     │
                              └─────────────────┘
         │
         └─── POST /webhooks/rest/webhook ────┐
                                               │
                                      ┌────────▼────────┐
                                      │  Rasa Server    │
                                      │  (Port 5005)    │
                                      └────────┬────────┘
                                               │
                                      ┌────────▼────────┐
                                      │ Actions Server   │
                                      └─────────────────┘
```

## Features

### Gaze Detection

Detects gaze direction:
- `forward` - Looking at camera
- `away` - Looking away
- `down` - Looking down
- `left` - Looking left
- `right` - Looking right
- `up` - Looking up

### Expression Detection

Detects micro-expressions:
- `neutral` - Neutral expression
- `happy` - Happy/smiling
- `sad` - Sad/frowning
- `fear` - Fear/anxiety
- `anger` - Angry
- `surprise` - Surprised
- `disgust` - Disgusted

## Development

### Enable Auto-reload

For development, enable auto-reload:

```bash
python run_vision_server.py --reload
```

### Debug Mode

Set environment variable for debug logging:

```bash
export ACTIONS_LOG_LEVEL=DEBUG
python run_vision_server.py
```

## Support

For issues or questions, check:
1. The setup and test script output
2. Server logs for error messages
3. Browser console for frontend errors

