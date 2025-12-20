"""
Vision API Server

FastAPI server that handles:
- POST /ingest-frame: Receives video frames and processes them
- GET /latest-signals: Returns the latest gaze and expression signals
- GET /health: Health check endpoint
"""

import os
import time
import logging
from typing import Dict, Optional
from fastapi import FastAPI, UploadFile, File, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import uvicorn
import numpy as np
from PIL import Image
import io
import threading
from collections import defaultdict
from datetime import datetime

import sys
import os

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from microexpression_detector import MicroexpressionDetector

# Environment configuration
ENV = os.getenv("ENV", "development").lower()
DEBUG = ENV == "development"
LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO

# Configure logging
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Dental Chatbot Vision API",
    version="1.0.0",
    description="Real-time facial expression and gaze detection API",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None
)

# CORS configuration
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",") if os.getenv("ALLOWED_ORIGINS") else ["*"]
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",") if os.getenv("ALLOWED_HOSTS") else ["*"]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Add trusted host middleware for production
if not DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=ALLOWED_HOSTS
    )

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    if not DEBUG:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Initialize detector
detector = MicroexpressionDetector()

# Store latest signals per sender
# Format: {sender_id: {"gaze_state": str, "micro_expression": str, "timestamp": float}}
signals_cache: Dict[str, Dict[str, any]] = defaultdict(lambda: {
    "gaze_state": "neutral",
    "micro_expression": "neutral",
    "timestamp": 0.0
})

# Thread lock for thread-safe access
cache_lock = threading.Lock()

# Rate limiting (simple in-memory implementation)
rate_limit_store: Dict[str, list] = defaultdict(list)
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "100"))  # per window

def check_rate_limit(sender_id: str) -> bool:
    """Check if sender has exceeded rate limit."""
    now = time.time()
    # Clean old entries
    rate_limit_store[sender_id] = [
        t for t in rate_limit_store[sender_id] 
        if now - t < RATE_LIMIT_WINDOW
    ]
    # Check limit
    if len(rate_limit_store[sender_id]) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    # Add current request
    rate_limit_store[sender_id].append(now)
    return True

# Serve static files and templates
static_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_integration", "static")
templates_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_integration", "templates")

if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")
if os.path.exists(templates_path):
    templates = Jinja2Templates(directory=templates_path)


def image_to_numpy(image_bytes: bytes) -> Optional[np.ndarray]:
    """Convert image bytes to numpy array (BGR format for OpenCV)."""
    try:
        # Load image from bytes
        image = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')
        # Convert to numpy array
        img_array = np.array(image)
        # Convert RGB to BGR for OpenCV
        img_array = img_array[:, :, ::-1]
        return img_array
    except Exception as e:
        logger.error(f"Error converting image: {e}")
        return None


@app.get("/")
async def root(request: Request):
    """Serve the main HTML page."""
    if templates and os.path.exists(templates_path):
        # Inject configuration into template
        rasa_url = os.getenv("RASA_SERVER_URL", "http://localhost:5005/webhooks/rest/webhook")
        vision_url = f"{request.url.scheme}://{request.url.netloc}"
        return templates.TemplateResponse("index.html", {
            "request": request,
            "rasa_url": rasa_url,
            "vision_url": vision_url,
            "environment": ENV
        })
    return JSONResponse({"message": "Vision API is running. Use /health to check status."})


@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        # Quick detector test
        test_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        detector.detect(test_frame)
        detector_status = "ok"
    except Exception as e:
        logger.warning(f"Detector health check failed: {e}")
        detector_status = "error"
    
    return JSONResponse({
        "status": "healthy" if detector_status == "ok" else "degraded",
        "service": "vision-api",
        "version": "1.0.0",
        "detector": detector_status,
        "active_senders": len(signals_cache),
        "timestamp": time.time(),
        "environment": ENV
    })


@app.post("/ingest-frame")
async def ingest_frame(
    file: UploadFile = File(...),
    x_sender: Optional[str] = Header(None, alias="X-Sender")
):
    """
    Receive a video frame and process it for gaze and expression detection.
    
    Args:
        file: Image file (JPEG/PNG)
        x_sender: Sender ID from header
        
    Returns:
        JSON response with detection results
    """
    sender_id = x_sender or "unknown"
    
    # Rate limiting
    if not check_rate_limit(sender_id):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds."
        )
    
    # Validate file size (max 5MB)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    try:
        file_size = 0
        content = await file.read()
        file_size = len(content)
        
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE / 1024 / 1024}MB"
            )
        
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Empty image file")
        
        # Reset file pointer for processing
        await file.seek(0)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=400, detail="Invalid file")
    
    try:
        # Read image bytes
        image_bytes = await file.read()
        
        if len(image_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty image file")
        
        # Convert to numpy array
        frame = image_to_numpy(image_bytes)
        
        if frame is None:
            raise HTTPException(status_code=400, detail="Failed to decode image")
        
        # Detect gaze and expression
        results = detector.detect(frame)
        
        # Calculate emotion weight (combination of confidence, intensity, and engagement)
        expression_intensity = results.get("expression_intensity", 0.0)
        expression_confidence = results.get("expression_confidence", 0.5)
        engagement_level = results.get("engagement_level", 0.5)
        emotion_weight = (expression_confidence * expression_intensity + engagement_level) / 2.0
        
        # Update cache with thread-safe access
        with cache_lock:
            signals_cache[sender_id] = {
                "gaze_state": results.get("gaze_state", "neutral"),
                "micro_expression": results.get("micro_expression", "neutral"),
                "expression_confidence": expression_confidence,
                "expression_intensity": expression_intensity,
                "gaze_confidence": results.get("gaze_confidence", 0.5),
                "engagement_level": engagement_level,
                "emotion_weight": emotion_weight,
                "timestamp": time.time()
            }
        
        logger.debug(f"Processed frame for {sender_id}: {results}")
        
        # Calculate emotion weight for response
        expression_intensity = results.get("expression_intensity", 0.0)
        expression_confidence = results.get("expression_confidence", 0.5)
        engagement_level = results.get("engagement_level", 0.5)
        emotion_weight = (expression_confidence * expression_intensity + engagement_level) / 2.0
        
        return JSONResponse({
            "status": "success",
            "gaze_state": results.get("gaze_state", "neutral"),
            "micro_expression": results.get("micro_expression", "neutral"),
            "expression_confidence": expression_confidence,
            "expression_intensity": expression_intensity,
            "gaze_confidence": results.get("gaze_confidence", 0.5),
            "engagement_level": engagement_level,
            "emotion_weight": emotion_weight,
            "sender_id": sender_id
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing frame: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/latest-signals")
async def latest_signals(x_sender: Optional[str] = Header(None, alias="X-Sender")):
    """
    Get the latest gaze and expression signals for a sender.
    
    Args:
        x_sender: Sender ID from header
        
    Returns:
        JSON with gaze_state and micro_expression
    """
    sender_id = x_sender or "unknown"
    
    with cache_lock:
        signals = signals_cache.get(sender_id, {
            "gaze_state": "neutral",
            "micro_expression": "neutral",
            "expression_confidence": 0.5,
            "expression_intensity": 0.0,
            "gaze_confidence": 0.5,
            "engagement_level": 0.5,
            "timestamp": 0.0
        })
    
    # Return signals with emotion weights
    expression_intensity = signals.get("expression_intensity", 0.0)
    expression_confidence = signals.get("expression_confidence", 0.5)
    engagement_level = signals.get("engagement_level", 0.5)
    emotion_weight = signals.get("emotion_weight", (expression_confidence * expression_intensity + engagement_level) / 2.0)
    
    return JSONResponse({
        "gaze_state": signals.get("gaze_state", "neutral"),
        "micro_expression": signals.get("micro_expression", "neutral"),
        "expression_confidence": expression_confidence,
        "expression_intensity": expression_intensity,
        "gaze_confidence": signals.get("gaze_confidence", 0.5),
        "engagement_level": engagement_level,
        "emotion_weight": emotion_weight,
        "sender_id": sender_id
    })


@app.get("/stats")
async def stats():
    """Get statistics about active senders (for debugging)."""
    with cache_lock:
        active_senders = len(signals_cache)
        total_requests = sum(1 for s in signals_cache.values() if s.get("timestamp", 0) > time.time() - 60)
    
    return JSONResponse({
        "active_senders": active_senders,
        "recent_activity": total_requests,
        "timestamp": time.time()
    })


if __name__ == "__main__":
    import sys
    # Ensure we can import microexpression_detector
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    port = int(os.getenv("VISION_API_PORT", "8081"))
    host = os.getenv("VISION_API_HOST", "0.0.0.0")
    
    logger.info(f"Starting Vision API server on {host}:{port}")
    logger.info(f"Access the web interface at: http://localhost:{port}")
    logger.info(f"Health check: http://localhost:{port}/health")
    
    uvicorn.run(app, host=host, port=port, log_level="info")

