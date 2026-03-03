"""
Vision API Server v2.0

FastAPI server that handles:
- POST /ingest-frame: Receives video frames and processes them
- GET /latest-signals: Returns the latest gaze and expression signals
- POST /chat: Emotion-aware chat proxy (frontend -> vision server -> Rasa)
- GET /health: Health check endpoint
"""

import os
import sys
import time
import random
import logging
from typing import Dict, Optional
from fastapi import FastAPI, UploadFile, File, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import httpx
import uvicorn
import numpy as np
from PIL import Image
import io
import threading
from collections import defaultdict
from pydantic import BaseModel

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

# Rasa configuration
RASA_BASE = os.getenv("RASA_SERVER_URL", "http://localhost:5005")
RASA_WEBHOOK_URL = f"{RASA_BASE}/webhooks/rest/webhook"
RASA_PARSE_URL = f"{RASA_BASE}/model/parse"

# Initialize FastAPI app
app = FastAPI(
    title="Dental Chatbot Vision API",
    version="2.0.0",
    description="Real-time facial expression detection + emotion-aware chat proxy",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None
)

# CORS configuration
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",") if os.getenv("ALLOWED_ORIGINS") else ["*"]
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",") if os.getenv("ALLOWED_HOSTS") else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

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

# Default signal template
_DEFAULT_SIGNAL = {
    "gaze_state": "neutral",
    "micro_expression": "neutral",
    "expression_confidence": 0.5,
    "expression_intensity": 0.0,
    "gaze_confidence": 0.5,
    "engagement_level": 0.5,
    "emotion_weight": 0.0,
    "emotion_distribution": {},
    "timestamp": 0.0,
}

# Store latest signals per sender
signals_cache: Dict[str, Dict] = defaultdict(lambda: dict(_DEFAULT_SIGNAL))

# Thread lock for thread-safe access
cache_lock = threading.Lock()

# Rate limiting
rate_limit_store: Dict[str, list] = defaultdict(list)
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "100"))


def check_rate_limit(sender_id: str) -> bool:
    now = time.time()
    rate_limit_store[sender_id] = [
        t for t in rate_limit_store[sender_id]
        if now - t < RATE_LIMIT_WINDOW
    ]
    if len(rate_limit_store[sender_id]) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    rate_limit_store[sender_id].append(now)
    return True


# Serve static files and templates
static_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_integration", "static")
templates_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web_integration", "templates")

templates = None
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")
if os.path.exists(templates_path):
    templates = Jinja2Templates(directory=templates_path)


def image_to_numpy(image_bytes: bytes) -> Optional[np.ndarray]:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != 'RGB':
            image = image.convert('RGB')
        img_array = np.array(image)
        img_array = img_array[:, :, ::-1]
        return img_array
    except Exception as e:
        logger.error(f"Error converting image: {e}")
        return None


# ── Emotion-weighted response matrix ────────────────────────────────────

EMOTION_RESPONSES = {
    ("greet", "happy"): [
        "Hey there! Great to see you smiling! How can I help with your dental care today?",
        "Hello! You look wonderful today! What can I do for you?",
    ],
    ("greet", "anxious"): [
        "Hello! I can see you might be a bit nervous, and that's completely okay. I'm here to help you feel comfortable. What can I assist you with?",
        "Hi there! Don't worry, I'm here to make things easy for you. What's on your mind?",
    ],
    ("greet", "angry"): [
        "Hello! I understand things might be frustrating. I'm here to help sort things out for you. What do you need?",
        "Hi! I'm ready to help resolve whatever's bothering you. What can I do?",
    ],
    ("greet", "neutral"): [
        "Hello! Welcome to our dental clinic. How can I assist you today?",
    ],
    ("ask_services", "happy"): [
        "Great question! We offer cleanings, whitening, fillings, orthodontics, and cosmetic dentistry. What interests you?",
    ],
    ("ask_services", "anxious"): [
        "We offer many services, and I want to make sure you're comfortable with whatever you choose. Our options include gentle cleanings, whitening, and more. Would you like details on any specific service?",
    ],
    ("ask_services", "angry"): [
        "I understand you want clear answers. We offer: cleanings, whitening, fillings, braces, and cosmetic work. Which one do you need help with?",
    ],
    ("book_appointment", "happy"): [
        "Wonderful! Let's get you booked in! I'll need your name, phone number, and preferred date.",
    ],
    ("book_appointment", "anxious"): [
        "I'll help you book an appointment, and don't worry - our team is very gentle and understanding. I just need your name, phone number, and when you'd like to come in.",
    ],
    ("book_appointment", "angry"): [
        "Let's get this sorted out quickly. I'll need your name, phone number, and preferred date to book you in.",
    ],
    ("express_anxiety", "anxious"): [
        "I completely understand your feelings, and they're perfectly valid. Many of our patients feel the same way. Our team specializes in making anxious patients feel safe and comfortable. Would you like to know about our comfort options?",
        "It's okay to feel nervous - dental anxiety is very common. We have gentle techniques and can go at your pace. What specific concern can I address for you?",
    ],
    ("express_anxiety", "happy"): [
        "Thank you for sharing that with me! It's great that you're being open about it. We have many ways to make your visit comfortable.",
    ],
    ("ask_pricing", "anxious"): [
        "I understand cost can be a concern on top of everything else. Let me help you understand our pricing clearly so there are no surprises. What service are you looking at?",
    ],
    ("ask_pricing", "angry"): [
        "I'll give you straightforward pricing information with no hidden costs. Which service would you like to know about?",
    ],
    ("ask_pricing", "happy"): [
        "Sure! I'd be happy to share our pricing. Which service are you interested in?",
    ],
    ("ask_opening_hours", "neutral"): [
        "We're open Monday to Saturday, 9 AM to 6 PM. Would you like to schedule a visit?",
    ],
    ("ask_opening_hours", "anxious"): [
        "We're open Monday to Saturday, 9 AM to 6 PM. We can find a quieter time slot for your visit if you prefer. Would you like to book?",
    ],
    ("goodbye", "happy"): [
        "Goodbye! It was great chatting with you! Take care of that beautiful smile!",
    ],
    ("goodbye", "anxious"): [
        "Goodbye! Remember, there's nothing to worry about. We'll take great care of you when you visit!",
    ],
    ("goodbye", "neutral"): [
        "Goodbye! Don't hesitate to reach out if you need anything. Have a great day!",
    ],
    ("affirm", "happy"): [
        "Awesome! Let's move forward!",
    ],
    ("affirm", "anxious"): [
        "Great, we'll take it step by step. You're doing great!",
    ],
    ("deny", "angry"): [
        "No problem at all. What would you prefer instead?",
    ],
    ("thank", "happy"): [
        "You're so welcome! It's a pleasure helping you!",
    ],
    ("thank", "anxious"): [
        "You're welcome! I'm always here if you need anything else. Don't hesitate to ask!",
    ],
}


def _map_emotion_group(expression: str) -> str:
    """Map detected expression to emotion group for response lookup."""
    expr = expression.lower().strip()
    if expr in ("fear", "sad", "disgust"):
        return "anxious"
    if expr in ("anger", "angry"):
        return "angry"
    if expr == "happy":
        return "happy"
    return "neutral"


def _apply_emotion_weighting(rasa_responses: list, intent: str,
                              expression: str, confidence: float,
                              intensity: float) -> list:
    """Apply emotion-weighted response selection.

    weight > 0.7  -> fully replace with emotion-specific response
    0.35 < weight <= 0.7 -> prepend emotion-aware text, then Rasa content
    weight <= 0.35 -> pass Rasa response through unchanged
    """
    emotion_weight = confidence * intensity
    emotion_group = _map_emotion_group(expression)

    key = (intent, emotion_group)
    emotion_variants = EMOTION_RESPONSES.get(key)

    if emotion_weight > 0.7 and emotion_variants:
        chosen = random.choice(emotion_variants)
        return [{"text": chosen}]

    if 0.35 < emotion_weight <= 0.7 and emotion_variants:
        prefix = random.choice(emotion_variants)
        rasa_texts = " ".join(r.get("text", "") for r in rasa_responses if r.get("text"))
        if rasa_texts:
            return [{"text": f"{prefix}\n\n{rasa_texts}"}]
        return [{"text": prefix}]

    return rasa_responses


# ── Request model for /chat ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    sender: str
    message: str


# ── Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def root(request: Request):
    if templates and os.path.exists(templates_path):
        vision_url = f"{request.url.scheme}://{request.url.netloc}"
        return templates.TemplateResponse("index.html", {
            "request": request,
            "vision_url": vision_url,
            "environment": ENV
        })
    return JSONResponse({"message": "Vision API is running. Use /health to check status."})


@app.get("/health")
async def health():
    try:
        test_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        detector.detect(test_frame)
        detector_status = "ok"
    except Exception as e:
        logger.warning(f"Detector health check failed: {e}")
        detector_status = "error"

    return JSONResponse({
        "status": "healthy" if detector_status == "ok" else "degraded",
        "service": "vision-api",
        "version": "2.0.0",
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
    sender_id = x_sender or "unknown"

    if not check_rate_limit(sender_id):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds."
        )

    MAX_FILE_SIZE = 5 * 1024 * 1024
    try:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large. Maximum size is 5MB")
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty image file")
        await file.seek(0)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=400, detail="Invalid file")

    try:
        image_bytes = await file.read()
        if len(image_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty image file")

        frame = image_to_numpy(image_bytes)
        if frame is None:
            raise HTTPException(status_code=400, detail="Failed to decode image")

        results = detector.detect(frame)

        expression_intensity = results.get("expression_intensity", 0.0)
        expression_confidence = results.get("expression_confidence", 0.5)
        engagement_level = results.get("engagement_level", 0.5)
        emotion_weight = (expression_confidence * expression_intensity + engagement_level) / 2.0
        emotion_distribution = results.get("emotion_distribution", {})

        with cache_lock:
            signals_cache[sender_id] = {
                "gaze_state": results.get("gaze_state", "neutral"),
                "micro_expression": results.get("micro_expression", "neutral"),
                "expression_confidence": expression_confidence,
                "expression_intensity": expression_intensity,
                "gaze_confidence": results.get("gaze_confidence", 0.5),
                "engagement_level": engagement_level,
                "emotion_weight": emotion_weight,
                "emotion_distribution": emotion_distribution,
                "timestamp": time.time()
            }

        logger.debug(f"Processed frame for {sender_id}: {results}")

        return JSONResponse({
            "status": "success",
            "gaze_state": results.get("gaze_state", "neutral"),
            "micro_expression": results.get("micro_expression", "neutral"),
            "expression_confidence": expression_confidence,
            "expression_intensity": expression_intensity,
            "gaze_confidence": results.get("gaze_confidence", 0.5),
            "engagement_level": engagement_level,
            "emotion_weight": emotion_weight,
            "emotion_distribution": emotion_distribution,
            "sender_id": sender_id
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing frame: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/latest-signals")
async def latest_signals(x_sender: Optional[str] = Header(None, alias="X-Sender")):
    sender_id = x_sender or "unknown"

    with cache_lock:
        signals = signals_cache.get(sender_id, dict(_DEFAULT_SIGNAL))

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
        "emotion_distribution": signals.get("emotion_distribution", {}),
        "sender_id": sender_id
    })


@app.post("/chat")
async def chat_proxy(req: ChatRequest):
    """
    Emotion-aware chat proxy.

    1. Reads current emotion from signals_cache for this sender
    2. Forwards message to Rasa with emotion metadata
    3. Applies emotion-weighted response selection
    4. Returns enriched response
    """
    sender_id = req.sender or "unknown"
    message = req.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long")

    # Get current emotion for this sender
    with cache_lock:
        signals = signals_cache.get(sender_id, dict(_DEFAULT_SIGNAL))

    expression = signals.get("micro_expression", "neutral")
    expression_confidence = signals.get("expression_confidence", 0.5)
    expression_intensity = signals.get("expression_intensity", 0.0)
    engagement_level = signals.get("engagement_level", 0.5)
    emotion_distribution = signals.get("emotion_distribution", {})
    emotion_weight = signals.get("emotion_weight", 0.0)

    emotion_payload = {
        "expression": expression,
        "confidence": expression_confidence,
        "intensity": expression_intensity,
        "engagement": engagement_level,
        "distribution": emotion_distribution,
        "weight": emotion_weight,
    }

    logger.info(
        f"[chat] sender={sender_id} msg={message!r} emotion={expression} "
        f"conf={expression_confidence:.2f} intensity={expression_intensity:.2f}"
    )

    # Parse intent from Rasa
    intent = "unknown"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            parse_res = await client.post(RASA_PARSE_URL, json={"text": message})
            if parse_res.status_code == 200:
                parse_data = parse_res.json()
                intent = parse_data.get("intent", {}).get("name", "unknown")
    except Exception as e:
        logger.warning(f"[chat] Rasa parse failed: {e}")

    # Forward to Rasa webhook with emotion metadata
    rasa_responses = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            rasa_res = await client.post(RASA_WEBHOOK_URL, json={
                "sender": sender_id,
                "message": message,
                "metadata": {"emotion": emotion_payload},
            })
            if rasa_res.status_code == 200:
                rasa_responses = rasa_res.json()
                if not isinstance(rasa_responses, list):
                    rasa_responses = [rasa_responses] if rasa_responses else []
    except Exception as e:
        logger.error(f"[chat] Rasa webhook failed: {e}")
        rasa_responses = [{"text": "I'm sorry, I couldn't reach the assistant. Please try again."}]

    if not rasa_responses:
        rasa_responses = [{"text": "I received your message but didn't get a response. Please try again."}]

    # Apply emotion-weighted response selection
    final_responses = _apply_emotion_weighting(
        rasa_responses, intent, expression, expression_confidence, expression_intensity
    )

    return JSONResponse({
        "responses": final_responses,
        "emotion": emotion_payload,
        "intent": intent,
        "sender_id": sender_id,
    })


@app.get("/stats")
async def stats():
    with cache_lock:
        active_senders = len(signals_cache)
        total_requests = sum(1 for s in signals_cache.values() if s.get("timestamp", 0) > time.time() - 60)

    return JSONResponse({
        "active_senders": active_senders,
        "recent_activity": total_requests,
        "timestamp": time.time()
    })


if __name__ == "__main__":
    port = int(os.getenv("VISION_API_PORT", "8081"))
    host = os.getenv("VISION_API_HOST", "0.0.0.0")

    logger.info(f"Starting Vision API server on {host}:{port}")
    logger.info(f"Access the web interface at: http://localhost:{port}")
    logger.info(f"Health check: http://localhost:{port}/health")

    uvicorn.run(app, host=host, port=port, log_level="info")
