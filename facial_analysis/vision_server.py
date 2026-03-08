"""
Vision API Server v3.1

FastAPI server with advanced emotion-aware chat intelligence:
- POST /ingest-frame: Receives video frames and processes them
- GET /latest-signals: Returns the latest gaze and expression signals
- POST /chat: Emotion-aware chat proxy with standalone fallback
- GET /health: Health check endpoint
- GET /emotion-history: Returns emotion trajectory for a sender

v3.1: Standalone smart response engine - works without Rasa dependency.
"""

import os
import sys
import time
import re
import random
import logging
import math
from typing import Dict, List, Optional, Tuple
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
from collections import defaultdict, deque
from pydantic import BaseModel

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from microexpression_detector import MicroexpressionDetector

# Environment configuration
ENV = os.getenv("ENV", "development").lower()
DEBUG = ENV == "development"
LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO

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

# Initialize FastAPI
app = FastAPI(
    title="Dental Chatbot Vision API",
    version="3.1.0",
    description="Advanced emotion detection + intelligent chat proxy",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None
)

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
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


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
    "compound_emotion": None,
    "compound_confidence": 0.0,
    "micro_expression_spike": None,
    "spike_intensity": 0.0,
    "head_pitch": 0.0,
    "head_yaw": 0.0,
    "head_roll": 0.0,
    "valence": 0.0,
    "arousal": 0.0,
    "timestamp": 0.0,
}

# Store latest signals per sender
signals_cache: Dict[str, Dict] = defaultdict(lambda: dict(_DEFAULT_SIGNAL))
cache_lock = threading.Lock()

# ── Emotion trajectory tracking ──────────────────────────────────────────
TRAJECTORY_MAX_LEN = 50  # keep last 50 readings per sender

emotion_trajectories: Dict[str, deque] = defaultdict(
    lambda: deque(maxlen=TRAJECTORY_MAX_LEN)
)
trajectory_lock = threading.Lock()

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


# ── Emotion Trajectory Analysis ──────────────────────────────────────────

def _compute_sentiment_momentum(trajectory: deque) -> Dict:
    """
    Analyze emotion trajectory to detect trends.
    Returns momentum metrics: direction, velocity, dominant_trend.
    """
    if len(trajectory) < 3:
        return {
            "direction": "stable",
            "velocity": 0.0,
            "dominant_trend": "neutral",
            "anxiety_trend": "stable",
            "engagement_trend": "stable",
        }

    recent = list(trajectory)
    n = len(recent)

    # Split into halves for comparison
    mid = n // 2
    first_half = recent[:mid]
    second_half = recent[mid:]

    # Valence trend
    avg_valence_early = sum(r.get("valence", 0) for r in first_half) / len(first_half)
    avg_valence_late = sum(r.get("valence", 0) for r in second_half) / len(second_half)
    valence_delta = avg_valence_late - avg_valence_early

    # Arousal trend
    avg_arousal_early = sum(r.get("arousal", 0) for r in first_half) / len(first_half)
    avg_arousal_late = sum(r.get("arousal", 0) for r in second_half) / len(second_half)
    arousal_delta = avg_arousal_late - avg_arousal_early

    # Engagement trend
    avg_eng_early = sum(r.get("engagement_level", 0.5) for r in first_half) / len(first_half)
    avg_eng_late = sum(r.get("engagement_level", 0.5) for r in second_half) / len(second_half)

    # Anxiety trend (fear + sad + disgust intensity)
    anxiety_emotions = {"fear", "sad", "disgust"}

    def anxiety_score(reading):
        dist = reading.get("emotion_distribution", {})
        return sum(dist.get(e, 0) for e in anxiety_emotions)

    avg_anxiety_early = sum(anxiety_score(r) for r in first_half) / len(first_half)
    avg_anxiety_late = sum(anxiety_score(r) for r in second_half) / len(second_half)
    anxiety_delta = avg_anxiety_late - avg_anxiety_early

    # Direction classification
    if valence_delta > 0.1:
        direction = "improving"
    elif valence_delta < -0.1:
        direction = "declining"
    else:
        direction = "stable"

    # Anxiety trend
    if anxiety_delta > 0.05:
        anxiety_trend = "increasing"
    elif anxiety_delta < -0.05:
        anxiety_trend = "decreasing"
    else:
        anxiety_trend = "stable"

    # Engagement trend
    eng_delta = avg_eng_late - avg_eng_early
    if eng_delta > 0.05:
        engagement_trend = "increasing"
    elif eng_delta < -0.05:
        engagement_trend = "decreasing"
    else:
        engagement_trend = "stable"

    # Dominant emotion in recent frames
    emotion_counts: Dict[str, float] = defaultdict(float)
    for r in second_half:
        expr = r.get("micro_expression", "neutral")
        emotion_counts[expr] += 1
    dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"

    return {
        "direction": direction,
        "velocity": abs(valence_delta),
        "dominant_trend": dominant,
        "anxiety_trend": anxiety_trend,
        "engagement_trend": engagement_trend,
        "valence_delta": round(valence_delta, 3),
        "arousal_delta": round(arousal_delta, 3),
        "avg_valence": round(avg_valence_late, 3),
        "avg_arousal": round(avg_arousal_late, 3),
        "avg_engagement": round(avg_eng_late, 3),
    }


# ── Emotion-weighted response matrix (expanded) ─────────────────────────
# 6 emotion groups: happy, anxious, angry, sad, surprised, neutral
# + compound-aware responses

EMOTION_RESPONSES = {
    # ── Greetings ──────────────────────────────────────────
    ("greet", "happy"): [
        "Hey there! Great to see you smiling! How can I help with your dental care today?",
        "Hello! You look wonderful today! What can I do for you?",
        "Hi! Your positive energy is contagious! What dental service are you interested in?",
    ],
    ("greet", "anxious"): [
        "Hello! I can see you might be a bit nervous, and that's completely okay. I'm here to help you feel comfortable. What can I assist you with?",
        "Hi there! Don't worry, I'm here to make things easy for you. What's on your mind?",
        "Hello! Take a deep breath - you're in good hands. I'm here to help at your own pace.",
    ],
    ("greet", "angry"): [
        "Hello! I understand things might be frustrating. I'm here to help sort things out for you. What do you need?",
        "Hi! I'm ready to help resolve whatever's bothering you. What can I do?",
    ],
    ("greet", "sad"): [
        "Hello! I'm here to help make things better. Whatever's on your mind, we can work through it together.",
        "Hi there. I'm here to support you. What can I help you with today?",
    ],
    ("greet", "surprised"): [
        "Hello! Welcome to our dental clinic! I'm ready to answer any questions you might have.",
        "Hi there! Glad you found us! How can I help you today?",
    ],
    ("greet", "neutral"): [
        "Hello! Welcome to our dental clinic. How can I assist you today?",
    ],

    # ── Services ───────────────────────────────────────────
    ("ask_services", "happy"): [
        "Great question! We offer cleanings, whitening, fillings, orthodontics, implants, and cosmetic dentistry. What excites you most?",
        "Wonderful! We have a full range of services. What catches your eye?",
    ],
    ("ask_services", "anxious"): [
        "We offer many gentle services, and I want to make sure you're comfortable. Our options include cleanings, whitening, fillings, and more. Would you like me to explain any specific one in detail?",
        "No rush at all. We have cleanings, checkups, whitening, fillings, and more. I can walk you through any of them step by step.",
    ],
    ("ask_services", "angry"): [
        "I understand you want clear answers. We offer: cleanings, whitening, fillings, braces, implants, and cosmetic work. Which one do you need help with?",
    ],
    ("ask_services", "sad"): [
        "We're here to help you feel better about your dental health. We offer cleanings, checkups, whitening, fillings, and more. What would help you most right now?",
    ],
    ("ask_services", "neutral"): [
        "We offer checkups, cleanings, whitening, fillings, braces, implants, and cosmetic dentistry. What interests you?",
    ],

    # ── Booking ────────────────────────────────────────────
    ("book_appointment", "happy"): [
        "Wonderful! Let's get you booked! I'll need your name, phone number, and preferred date.",
        "Excellent! Let's set up your appointment. What's your name?",
    ],
    ("book_appointment", "anxious"): [
        "I'll help you book an appointment, and don't worry - our team is very gentle and understanding. I just need your name, phone number, and when you'd like to come in.",
        "No pressure at all. Let's take this step by step. First, can I get your name?",
    ],
    ("book_appointment", "angry"): [
        "Let's get this sorted out quickly. I'll need your name, phone number, and preferred date to book you in.",
    ],
    ("book_appointment", "sad"): [
        "I'll help you book an appointment. Our team is very caring and will make sure you're comfortable. Can I start with your name?",
    ],
    ("book_appointment", "neutral"): [
        "Sure! I'll need your name, phone number, and preferred date. Let's get started.",
    ],

    # ── Anxiety ────────────────────────────────────────────
    ("express_anxiety", "anxious"): [
        "I completely understand your feelings, and they're perfectly valid. Many of our patients feel the same way. Our team specializes in making anxious patients feel safe. Would you like to know about our comfort options?",
        "It's okay to feel nervous - dental anxiety is very common. We have gentle techniques, sedation options, and can go at your pace. What specific concern can I address?",
        "Your feelings are completely normal. We've helped many patients who felt the same way. We can start with just a conversation - no pressure at all.",
    ],
    ("express_anxiety", "happy"): [
        "Thank you for sharing that! It's great that you're being open. We have many ways to make your visit comfortable, and your positive attitude will help!",
    ],
    ("express_anxiety", "sad"): [
        "I hear you, and I want you to know it's okay to feel this way. We're here to support you every step of the way. Would talking through the process help ease your mind?",
    ],
    ("express_anxiety", "neutral"): [
        "Thank you for letting me know. Dental anxiety is more common than you think. We have comfort options including gentle techniques and sedation. What would help you most?",
    ],

    # ── Pricing ────────────────────────────────────────────
    ("ask_pricing", "anxious"): [
        "I understand cost can be a concern on top of everything else. Let me help you understand our pricing clearly so there are no surprises. What service are you looking at?",
    ],
    ("ask_pricing", "angry"): [
        "I'll give you straightforward pricing information with no hidden costs. Which service would you like to know about?",
    ],
    ("ask_pricing", "happy"): [
        "Sure! I'd be happy to share our pricing. Which service are you interested in?",
    ],
    ("ask_pricing", "sad"): [
        "Don't worry about the cost just yet. We have flexible options and payment plans. Which service are you considering?",
    ],
    ("ask_pricing", "neutral"): [
        "Pricing varies by treatment. Which service would you like pricing for?",
    ],

    # ── Hours ──────────────────────────────────────────────
    ("ask_hours", "anxious"): [
        "We're open Monday to Saturday, 9 AM to 6 PM. We can find a quieter time for your visit if you prefer. Would you like to book?",
    ],
    ("ask_hours", "neutral"): [
        "We're open Monday to Saturday, 9 AM to 6 PM. Would you like to schedule a visit?",
    ],

    # ── Goodbye ────────────────────────────────────────────
    ("goodbye", "happy"): [
        "Goodbye! It was great chatting with you! Take care of that beautiful smile!",
        "Bye! Your positivity brightened my day! See you soon!",
    ],
    ("goodbye", "anxious"): [
        "Goodbye! Remember, there's nothing to worry about. We'll take great care of you when you visit! You've got this!",
        "Take care! And remember - you're braver than you think. We'll make your visit as comfortable as possible.",
    ],
    ("goodbye", "sad"): [
        "Take care! I hope our conversation helped a bit. We're always here when you need us.",
    ],
    ("goodbye", "neutral"): [
        "Goodbye! Don't hesitate to reach out if you need anything. Have a great day!",
    ],

    # ── Affirmation ────────────────────────────────────────
    ("affirm", "happy"): ["Awesome! Let's move forward!"],
    ("affirm", "anxious"): ["Great, we'll take it step by step. You're doing great!"],
    ("affirm", "sad"): ["That's a brave step. I'm here with you."],

    # ── Denial ─────────────────────────────────────────────
    ("deny", "angry"): ["No problem at all. What would you prefer instead?"],
    ("deny", "anxious"): ["That's perfectly okay. There's no pressure at all. What would you like to do instead?"],
    ("deny", "sad"): ["That's alright. Take your time. What else can I help with?"],

    # ── Thanks ─────────────────────────────────────────────
    ("chitchat/thanks", "happy"): ["You're so welcome! It's a pleasure helping you!"],
    ("chitchat/thanks", "anxious"): ["You're welcome! I'm always here if you need anything. Don't hesitate to ask!"],
    ("chitchat/thanks", "sad"): ["You're welcome. I'm glad I could help. I'm always here for you."],

    # ── Concern ────────────────────────────────────────────
    ("express_concern", "anxious"): [
        "I hear your concern, and it's completely valid. Let me address it specifically so you feel more informed and comfortable. What's worrying you most?",
        "Your concerns matter to us deeply. Let's talk through each one at your pace.",
    ],
    ("express_concern", "angry"): [
        "I understand your frustration. Let me address your concerns directly and honestly. What's the main issue?",
    ],
    ("express_concern", "sad"): [
        "I can see this is weighing on you. Let's work through your concerns together. What's on your mind?",
    ],

    # ── Pain ───────────────────────────────────────────────
    ("express_pain", "anxious"): [
        "I'm so sorry you're in pain. Please don't worry - we can help. For immediate relief, call us and we'll prioritize your care.",
    ],
    ("express_pain", "angry"): [
        "I understand the pain is frustrating. Let's get you relief as fast as possible. Please call us for urgent care.",
    ],
    ("express_pain", "sad"): [
        "I'm sorry you're going through this. Pain can be really discouraging. We're here to help and will get you comfortable as soon as possible.",
    ],

    # ── Emergency ──────────────────────────────────────────
    ("request_emergency", "anxious"): [
        "Please stay calm - we handle emergencies every day. Call us right now and we'll get you in immediately. You're going to be okay.",
    ],
    ("request_emergency", "angry"): [
        "I understand the urgency. Please call us immediately and we'll prioritize your case. We're ready to help right now.",
    ],

    # ── Procedures ─────────────────────────────────────────
    ("consult_procedure_details", "anxious"): [
        "I'd be happy to explain the procedure in detail. Understanding each step often helps reduce anxiety. Which procedure would you like to know about? I'll walk you through it gently.",
    ],
    ("consult_procedure_details", "happy"): [
        "Great curiosity! I'd love to explain the details. Which procedure are you interested in?",
    ],
    ("query_procedure_risks", "anxious"): [
        "I understand wanting to know about risks - that's actually a sign of good preparation. Our procedures have very high success rates, and I'll be transparent about everything. What specific procedure are you considering?",
    ],
    ("query_procedure_risks", "angry"): [
        "I'll give you the straight facts on risks. Our team believes in full transparency. Which procedure would you like the risk profile for?",
    ],
}

# ── Momentum-aware response prefixes ────────────────────────────────────
MOMENTUM_PREFIXES = {
    ("improving", "anxious"): "I can see you're starting to feel a bit more comfortable, which is wonderful. ",
    ("declining", "anxious"): "I sense things might feel a bit overwhelming right now. Let's slow down. ",
    ("improving", "happy"): "",  # don't interrupt positive momentum
    ("declining", "happy"): "I want to make sure everything is going well. ",
    ("increasing_anxiety", "anxious"): "I notice you might be getting more worried. That's okay - let me help. ",
    ("decreasing_anxiety", "anxious"): "You seem to be feeling more at ease, and that's great! ",
    ("decreasing_engagement", "neutral"): "I want to make sure I'm being helpful. Would you like me to explain things differently? ",
}


def _map_emotion_group(expression: str, compound: Optional[str] = None) -> str:
    """Map detected expression to emotion group for response lookup (6 groups)."""
    # Compound emotions take priority
    if compound:
        compound_lower = compound.lower()
        if compound_lower in ("anxious", "nervous_disgust", "frustrated"):
            return "anxious"
        if compound_lower == "happily_surprised":
            return "happy"
        if compound_lower == "bittersweet":
            return "sad"

    expr = expression.lower().strip()
    if expr in ("fear", "disgust", "contempt"):
        return "anxious"
    if expr in ("angry",):
        return "angry"
    if expr in ("sad",):
        return "sad"
    if expr in ("happy",):
        return "happy"
    if expr in ("surprise",):
        return "surprised"
    return "neutral"


def _apply_emotion_weighting(rasa_responses: list, intent: str,
                              expression: str, confidence: float,
                              intensity: float,
                              compound: Optional[str] = None,
                              momentum: Optional[Dict] = None) -> list:
    """
    Apply emotion-weighted response selection with momentum awareness.

    weight > 0.6  -> fully replace with emotion-specific response
    0.30 < weight <= 0.6 -> prepend emotion-aware text, then Rasa content
    weight <= 0.30 -> pass Rasa response through unchanged
    Momentum prefix applied when trajectory detected.
    """
    emotion_weight = confidence * intensity
    emotion_group = _map_emotion_group(expression, compound)

    # Try exact match first, then fall back to neutral
    key = (intent, emotion_group)
    emotion_variants = EMOTION_RESPONSES.get(key)

    # Try "surprised" -> "neutral" fallback
    if not emotion_variants and emotion_group == "surprised":
        emotion_variants = EMOTION_RESPONSES.get((intent, "neutral"))

    # Apply momentum prefix if available
    momentum_prefix = ""
    if momentum:
        direction = momentum.get("direction", "stable")
        anxiety = momentum.get("anxiety_trend", "stable")
        engagement = momentum.get("engagement_trend", "stable")

        # Check specific momentum patterns
        if anxiety == "increasing" and emotion_group == "anxious":
            momentum_prefix = MOMENTUM_PREFIXES.get(("increasing_anxiety", "anxious"), "")
        elif anxiety == "decreasing" and emotion_group == "anxious":
            momentum_prefix = MOMENTUM_PREFIXES.get(("decreasing_anxiety", "anxious"), "")
        elif engagement == "decreasing":
            momentum_prefix = MOMENTUM_PREFIXES.get(("decreasing_engagement", "neutral"), "")
        else:
            momentum_prefix = MOMENTUM_PREFIXES.get((direction, emotion_group), "")

    if emotion_weight > 0.6 and emotion_variants:
        chosen = random.choice(emotion_variants)
        return [{"text": f"{momentum_prefix}{chosen}"}]

    if 0.30 < emotion_weight <= 0.6 and emotion_variants:
        prefix = random.choice(emotion_variants)
        rasa_texts = " ".join(r.get("text", "") for r in rasa_responses if r.get("text"))
        combined = f"{momentum_prefix}{prefix}"
        if rasa_texts:
            return [{"text": f"{combined}\n\n{rasa_texts}"}]
        return [{"text": combined}]

    # Low weight: pass through but add momentum prefix if relevant
    if momentum_prefix and emotion_weight > 0.15:
        rasa_texts = " ".join(r.get("text", "") for r in rasa_responses if r.get("text"))
        if rasa_texts:
            return [{"text": f"{momentum_prefix}{rasa_texts}"}]

    return rasa_responses


# ── Standalone Smart Response Engine ──────────────────────────────────────
# Keyword/pattern-based intent classifier + response generator.
# Handles common dental intents WITHOUT Rasa. Used as:
#   1. Primary fallback when Rasa is unreachable
#   2. Intent source when Rasa parse fails (for emotion weighting)

_INTENT_PATTERNS: List[Tuple[str, List[str], float]] = [
    # (intent_name, keyword_patterns, base_confidence)
    # Patterns are matched case-insensitively against the user message.
    # First match wins (ordered by specificity).

    # Emergency / urgent
    ("request_emergency", [
        r"\bemergenc", r"\bbroken\b", r"\bknocked\s+out",
        r"\bswollen", r"\bbleeding\s+(gum|mouth|tooth)",
        r"\bsevere\s+pain", r"\bcan'?t\s+stop\s+bleeding",
        r"\bchipped\b", r"\babscess", r"\bcracked\s+tooth",
    ], 0.90),

    # Pain
    ("express_pain", [
        r"\bpain", r"\bhurt", r"\bache", r"\bsore",
        r"\bthrobbing", r"\bsensitiv", r"\bdiscomfort",
        r"\bouch", r"\bagony", r"\btooth\s*ache",
    ], 0.85),

    # Anxiety / nervousness
    ("express_anxiety", [
        r"\bnervous", r"\bscared", r"\banxious", r"\bworried",
        r"\bafraid", r"\bfear", r"\bdread", r"\bterrif",
        r"\bfrightened", r"\bphobia", r"\bpanic",
        r"\bdon'?t\s+like\s+dentist", r"\bhate\s+dentist",
    ], 0.85),

    # Concern (note: "worried" is handled by express_anxiety above)
    ("express_concern", [
        r"\bconcern", r"\bnot\s+sure",
        r"\bis\s+it\s+(?:safe|normal|ok)", r"\bshould\s+i\s+be\s+worried",
    ], 0.80),

    # Booking
    ("book_appointment", [
        r"\bbook", r"\bappointment", r"\bschedul", r"\breserv",
        r"\bslot", r"\bavailab", r"\bcome\s+in", r"\bvisit",
        r"\bwhen\s+can\s+(?:i|we)", r"\bsee\s+(?:the\s+)?doctor",
        r"\bsign\s+(?:me\s+)?up",
    ], 0.85),

    # Pricing (before procedures so "whitening cost" matches pricing, not procedure)
    ("ask_pricing", [
        r"\bpric", r"\bcost", r"\bhow\s+much", r"\bfee",
        r"\bexpens", r"\bafford", r"\binsurance", r"\bpay",
        r"\bcharge", r"\bbudget", r"\bcheap",
    ], 0.85),

    # Services
    ("ask_services", [
        r"\bservices?", r"\btreatment", r"\bwhat\s+(?:do\s+you|can\s+you)\s+(?:offer|do|provide)",
        r"\bprocedure", r"\boptions?", r"\bwhat\s+(?:kind|type)",
    ], 0.82),

    # Procedure risks
    ("query_procedure_risks", [
        r"\brisk", r"\bside\s+effect", r"\bdanger", r"\bcomplica",
        r"\bwhat\s+(?:could|can|might)\s+go\s+wrong",
        r"\bis\s+it\s+(?:safe|risky)",
    ], 0.82),

    # Specific procedures
    ("consult_procedure_details", [
        r"\bwhiten", r"\bbleach", r"\bimplant", r"\bcrown",
        r"\bfilling", r"\broot\s+canal", r"\bextract", r"\bbraces",
        r"\borthodon", r"\bveneer", r"\bbridge", r"\bdenture",
        r"\bcleaning", r"\bscaling", r"\bx-?ray", r"\bexam",
        r"\bsealant", r"\bfluoride", r"\binvisalign",
    ], 0.80),

    # Hours / location
    ("ask_hours", [
        r"\bhours?\b", r"\bopen\b", r"\bclose\b", r"\bwhen\s+are\s+you",
        r"\bweekend", r"\bsaturday", r"\bsunday",
        r"\bwhat\s+(?:time|days)",
        r"\bworking\s+hours", r"\bopening\s+hours",
    ], 0.83),
    ("ask_location", [
        r"\bwhere\b", r"\blocation", r"\baddress", r"\bdirection",
        r"\bfind\s+you", r"\bmap",
    ], 0.83),

    # Greetings
    ("greet", [
        r"^h(?:i|ello|ey|owdy)\b", r"^good\s+(?:morning|afternoon|evening)",
        r"^what'?s\s+up", r"^yo\b", r"^greetings",
    ], 0.90),

    # Goodbye
    ("goodbye", [
        r"\bbye", r"\bgoodbye", r"\bsee\s+you", r"\btake\s+care",
        r"\bgood\s+night", r"\blater\b", r"\bfarewell",
    ], 0.90),

    # Deny (MUST be before thanks so "no thanks" matches deny, not thanks)
    ("deny", [
        r"^(?:no|nah|nope|not\s+(?:really|now|yet))\b",
        r"\bno\s+thank", r"\bno,?\s+thanks",
        r"\bdon'?t\s+(?:want|think|need)", r"\bi'?d\s+rather\s+not",
        r"\bmaybe\s+later", r"\bnot\s+interested",
    ], 0.85),

    # Thanks (after deny so "no thanks" doesn't match here)
    ("chitchat/thanks", [
        r"^thank", r"^thanks?\b", r"\bappreciate", r"\bgrateful",
        r"\bthx\b", r"\bty\b",
    ], 0.90),

    # Affirm
    ("affirm", [
        r"^(?:yes|yeah|yep|yup|sure|ok|okay|absolutely|definitely|of\s+course)\b",
        r"\bsounds\s+good", r"\bplease\s+do", r"\bgo\s+ahead",
    ], 0.85),
]

# Standalone responses for each intent (emotion-independent base responses)
_STANDALONE_RESPONSES: Dict[str, List[str]] = {
    "greet": [
        "Hello! Welcome to our dental clinic. How can I help you today?",
        "Hi there! I'm your dental care assistant. What can I do for you?",
    ],
    "goodbye": [
        "Goodbye! Take care of your teeth, and don't hesitate to reach out!",
        "Bye! Wishing you a healthy smile. See you soon!",
    ],
    "chitchat/thanks": [
        "You're welcome! Happy to help with your dental care needs.",
    ],
    "affirm": [
        "Great! Let's continue. What would you like to do next?",
    ],
    "deny": [
        "No problem at all. Is there anything else I can help you with?",
    ],
    "book_appointment": [
        "I'd be happy to help you book an appointment! Please call us at the clinic or visit our website to schedule. Our hours are Monday to Saturday, 9 AM to 6 PM.",
    ],
    "ask_services": [
        "We offer a wide range of dental services including:\n- General checkups and cleanings\n- Teeth whitening\n- Fillings and crowns\n- Root canal treatment\n- Orthodontics (braces, Invisalign)\n- Dental implants\n- Cosmetic dentistry (veneers, bonding)\n\nWhich service interests you?",
    ],
    "consult_procedure_details": [
        "I can help you understand dental procedures! We offer cleanings, fillings, crowns, root canals, extractions, whitening, braces, implants, and more. Which procedure would you like to know about in detail?",
    ],
    "query_procedure_risks": [
        "All dental procedures have very high success rates when performed by qualified professionals. Our team follows strict safety protocols. I'd be happy to discuss the specifics of any procedure you're considering. Which one are you interested in?",
    ],
    "ask_pricing": [
        "Pricing varies depending on the treatment needed. Here are general ranges:\n- Checkup & cleaning: affordable routine care\n- Fillings: varies by material and size\n- Whitening: cosmetic pricing available\n- Crowns/bridges: depends on material\n\nWe accept most insurance plans and offer payment plans. Which treatment would you like specific pricing for?",
    ],
    "ask_hours": [
        "We're open Monday through Saturday, 9:00 AM to 6:00 PM. Would you like to book a visit?",
    ],
    "ask_location": [
        "For our clinic location and directions, please check our website or give us a call. We'd be happy to help you find us!",
    ],
    "express_anxiety": [
        "It's completely normal to feel nervous about dental visits. You're not alone - many of our patients feel the same way. We specialize in gentle, patient-focused care and have comfort options including:\n- Detailed explanations before each step\n- Gentle techniques with modern equipment\n- Breaks whenever you need them\n- Sedation options for more complex procedures\n\nWould you like to know more about any of these comfort measures?",
    ],
    "express_pain": [
        "I'm sorry to hear you're in pain. Dental pain shouldn't be ignored as it can indicate an issue that needs attention. Here's what I recommend:\n- For mild pain: rinse with warm salt water and take over-the-counter pain relief\n- For moderate/severe pain: contact us for a priority appointment\n- For emergency pain: call us immediately\n\nHow severe is your pain?",
    ],
    "express_concern": [
        "Your concerns are completely valid and important to us. We believe in transparent, honest communication about dental care. What specific concern would you like me to address?",
    ],
    "request_emergency": [
        "For dental emergencies, please call us immediately. We prioritize emergency cases and will get you in as soon as possible.\n\nCommon emergencies we handle:\n- Knocked out or broken teeth\n- Severe pain or swelling\n- Uncontrolled bleeding\n- Dental abscess\n\nWhile you wait, keep the area clean, apply cold compress for swelling, and save any broken tooth fragments in milk.",
    ],
}

# Context-aware follow-up patterns
_FOLLOWUP_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "express_anxiety": {
        "anxious": [
            "I can see this is something you feel strongly about, and that's okay. Let me assure you - modern dentistry has come a very long way. Would you like me to walk you through exactly what happens during a visit, step by step?",
            "Your feelings matter to us. Many patients who were initially nervous end up feeling very comfortable after their first gentle visit. We go at your pace, always.",
        ],
    },
    "express_pain": {
        "anxious": [
            "I understand that pain combined with worry can feel overwhelming. I want you to know that treating the source of pain actually brings relief. Our team will make sure you're comfortable throughout. Would you like to schedule a gentle examination?",
        ],
    },
}


def _classify_intent_standalone(message: str) -> Tuple[str, float]:
    """
    Classify user intent using keyword/pattern matching.
    Returns (intent_name, confidence).
    """
    msg_lower = message.lower().strip()

    for intent_name, patterns, base_conf in _INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                return intent_name, base_conf

    return "unknown", 0.0


def _generate_standalone_response(intent: str, emotion_group: str,
                                   momentum: Optional[Dict] = None) -> Optional[str]:
    """
    Generate a smart response without Rasa.
    Tries emotion-specific response first, then standalone base, then None.
    """
    # Try emotion-specific response from the main EMOTION_RESPONSES matrix
    key = (intent, emotion_group)
    variants = EMOTION_RESPONSES.get(key)

    # Try context-aware follow-ups
    if not variants:
        followups = _FOLLOWUP_PATTERNS.get(intent, {})
        variants = followups.get(emotion_group)

    # Fall back to neutral emotion variant
    if not variants:
        variants = EMOTION_RESPONSES.get((intent, "neutral"))

    # Fall back to standalone responses
    if not variants:
        variants = _STANDALONE_RESPONSES.get(intent)

    if not variants:
        return None

    response = random.choice(variants)

    # Apply momentum prefix
    if momentum:
        direction = momentum.get("direction", "stable")
        anxiety = momentum.get("anxiety_trend", "stable")
        engagement = momentum.get("engagement_trend", "stable")

        prefix = ""
        if anxiety == "increasing" and emotion_group == "anxious":
            prefix = MOMENTUM_PREFIXES.get(("increasing_anxiety", "anxious"), "")
        elif anxiety == "decreasing" and emotion_group == "anxious":
            prefix = MOMENTUM_PREFIXES.get(("decreasing_anxiety", "anxious"), "")
        elif engagement == "decreasing":
            prefix = MOMENTUM_PREFIXES.get(("decreasing_engagement", "neutral"), "")
        elif direction != "stable":
            prefix = MOMENTUM_PREFIXES.get((direction, emotion_group), "")

        if prefix:
            response = f"{prefix}{response}"

    return response


def _generate_fallback_response(message: str, emotion_group: str,
                                  momentum: Optional[Dict] = None) -> str:
    """
    Generate an intelligent fallback when neither Rasa nor standalone
    intent matching can classify the message. Uses emotion-awareness
    to stay contextually appropriate.
    """
    emotion_fallbacks = {
        "anxious": [
            "I want to make sure I give you the right answer. Could you tell me a bit more about what you need? I'm here to help, no rush at all.",
            "I'm here for you. Could you rephrase that so I can help you better? Take your time.",
        ],
        "angry": [
            "I want to make sure I address your concern properly. Could you tell me specifically what you need help with?",
            "I hear you. Let me make sure I understand - could you clarify what you'd like me to help with?",
        ],
        "sad": [
            "I'm here to help. Could you tell me a bit more about what's on your mind? We'll figure it out together.",
        ],
        "happy": [
            "I'd love to help! Could you tell me a bit more about what you're looking for?",
        ],
        "neutral": [
            "I can help with appointments, services, pricing, procedures, and dental concerns. What would you like to know about?",
            "Could you tell me more about what you need? I'm here to help with anything dental-related.",
        ],
    }

    variants = emotion_fallbacks.get(emotion_group, emotion_fallbacks["neutral"])
    response = random.choice(variants)

    # Add momentum prefix for declining engagement
    if momentum and momentum.get("engagement_trend") == "decreasing":
        prefix = MOMENTUM_PREFIXES.get(("decreasing_engagement", "neutral"), "")
        if prefix:
            response = f"{prefix}{response}"

    return response


# ── Request models ───────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    sender: str
    message: str


# ── Endpoints ────────────────────────────────────────────────────────────

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
        "version": "3.1.0",
        "detector": detector_status,
        "active_senders": len(signals_cache),
        "timestamp": time.time(),
        "environment": ENV,
        "features": [
            "compound_emotions", "micro_expression_spikes",
            "head_pose", "valence_arousal", "sentiment_momentum",
            "adaptive_smoothing", "bayesian_confidence",
            "standalone_response_engine",
        ],
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=400, detail="Invalid file")

    try:
        frame = image_to_numpy(content)
        if frame is None:
            raise HTTPException(status_code=400, detail="Failed to decode image")

        results = detector.detect(frame)

        expression_intensity = results.get("expression_intensity", 0.0)
        expression_confidence = results.get("expression_confidence", 0.5)
        engagement_level = results.get("engagement_level", 0.5)
        emotion_weight = (expression_confidence * expression_intensity + engagement_level) / 2.0
        emotion_distribution = results.get("emotion_distribution", {})

        signal_data = {
            "gaze_state": results.get("gaze_state", "neutral"),
            "micro_expression": results.get("micro_expression", "neutral"),
            "expression_confidence": expression_confidence,
            "expression_intensity": expression_intensity,
            "gaze_confidence": results.get("gaze_confidence", 0.5),
            "engagement_level": engagement_level,
            "emotion_weight": emotion_weight,
            "emotion_distribution": emotion_distribution,
            "compound_emotion": results.get("compound_emotion"),
            "compound_confidence": results.get("compound_confidence", 0.0),
            "micro_expression_spike": results.get("micro_expression_spike"),
            "spike_intensity": results.get("spike_intensity", 0.0),
            "head_pitch": results.get("head_pitch", 0.0),
            "head_yaw": results.get("head_yaw", 0.0),
            "head_roll": results.get("head_roll", 0.0),
            "valence": results.get("valence", 0.0),
            "arousal": results.get("arousal", 0.0),
            "timestamp": time.time(),
        }

        with cache_lock:
            signals_cache[sender_id] = signal_data

        # Record in trajectory
        with trajectory_lock:
            emotion_trajectories[sender_id].append(dict(signal_data))

        logger.debug(f"Processed frame for {sender_id}: expr={results.get('micro_expression')} "
                     f"compound={results.get('compound_emotion')} spike={results.get('micro_expression_spike')}")

        return JSONResponse({
            "status": "success",
            **{k: v for k, v in signal_data.items() if k != "timestamp"},
            "sender_id": sender_id,
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

    return JSONResponse({
        "gaze_state": signals.get("gaze_state", "neutral"),
        "micro_expression": signals.get("micro_expression", "neutral"),
        "expression_confidence": signals.get("expression_confidence", 0.5),
        "expression_intensity": signals.get("expression_intensity", 0.0),
        "gaze_confidence": signals.get("gaze_confidence", 0.5),
        "engagement_level": signals.get("engagement_level", 0.5),
        "emotion_weight": signals.get("emotion_weight", 0.0),
        "emotion_distribution": signals.get("emotion_distribution", {}),
        "compound_emotion": signals.get("compound_emotion"),
        "compound_confidence": signals.get("compound_confidence", 0.0),
        "micro_expression_spike": signals.get("micro_expression_spike"),
        "spike_intensity": signals.get("spike_intensity", 0.0),
        "head_pitch": signals.get("head_pitch", 0.0),
        "head_yaw": signals.get("head_yaw", 0.0),
        "head_roll": signals.get("head_roll", 0.0),
        "valence": signals.get("valence", 0.0),
        "arousal": signals.get("arousal", 0.0),
        "sender_id": sender_id,
    })


@app.get("/emotion-history")
async def emotion_history(x_sender: Optional[str] = Header(None, alias="X-Sender")):
    """Returns emotion trajectory and momentum analysis for a sender."""
    sender_id = x_sender or "unknown"

    with trajectory_lock:
        trajectory = list(emotion_trajectories.get(sender_id, []))

    momentum = _compute_sentiment_momentum(deque(trajectory))

    # Summarize trajectory for frontend
    summary = []
    for reading in trajectory[-20:]:  # last 20 readings
        summary.append({
            "expression": reading.get("micro_expression", "neutral"),
            "valence": round(reading.get("valence", 0), 3),
            "arousal": round(reading.get("arousal", 0), 3),
            "engagement": round(reading.get("engagement_level", 0.5), 3),
            "compound": reading.get("compound_emotion"),
            "timestamp": reading.get("timestamp", 0),
        })

    return JSONResponse({
        "sender_id": sender_id,
        "momentum": momentum,
        "trajectory": summary,
        "total_readings": len(trajectory),
    })


@app.post("/chat")
async def chat_proxy(req: ChatRequest):
    """
    Advanced emotion-aware chat proxy.

    1. Reads current emotion + trajectory from signals cache
    2. Computes sentiment momentum
    3. Forwards message to Rasa with full emotion metadata
    4. Applies emotion-weighted + momentum-aware response selection
    5. Returns enriched response with emotion analytics
    """
    sender_id = req.sender or "unknown"
    message = req.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long")

    # Get current emotion
    with cache_lock:
        signals = signals_cache.get(sender_id, dict(_DEFAULT_SIGNAL))

    expression = signals.get("micro_expression", "neutral")
    expression_confidence = signals.get("expression_confidence", 0.5)
    expression_intensity = signals.get("expression_intensity", 0.0)
    engagement_level = signals.get("engagement_level", 0.5)
    emotion_distribution = signals.get("emotion_distribution", {})
    emotion_weight = signals.get("emotion_weight", 0.0)
    compound_emotion = signals.get("compound_emotion")
    compound_confidence = signals.get("compound_confidence", 0.0)
    spike = signals.get("micro_expression_spike")
    spike_intensity = signals.get("spike_intensity", 0.0)
    valence = signals.get("valence", 0.0)
    arousal = signals.get("arousal", 0.0)

    # Compute trajectory momentum
    with trajectory_lock:
        trajectory = emotion_trajectories.get(sender_id, deque())
    momentum = _compute_sentiment_momentum(trajectory)

    emotion_payload = {
        "expression": expression,
        "confidence": expression_confidence,
        "intensity": expression_intensity,
        "engagement": engagement_level,
        "distribution": emotion_distribution,
        "weight": emotion_weight,
        "compound_emotion": compound_emotion,
        "compound_confidence": compound_confidence,
        "micro_expression_spike": spike,
        "spike_intensity": spike_intensity,
        "valence": valence,
        "arousal": arousal,
        "momentum": momentum,
    }

    logger.info(
        f"[chat] sender={sender_id} msg={message!r} emotion={expression} "
        f"compound={compound_emotion} conf={expression_confidence:.2f} "
        f"intensity={expression_intensity:.2f} momentum={momentum.get('direction', 'stable')}"
    )

    # ── Intent classification ──────────────────────────────────────────
    # Try Rasa parse first, fall back to standalone classifier
    intent = "unknown"
    intent_confidence = 0.0
    rasa_available = True

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            parse_res = await client.post(RASA_PARSE_URL, json={"text": message})
            if parse_res.status_code == 200:
                parse_data = parse_res.json()
                intent = parse_data.get("intent", {}).get("name", "unknown")
                intent_confidence = parse_data.get("intent", {}).get("confidence", 0.0)
    except Exception as e:
        logger.warning(f"[chat] Rasa parse unavailable: {e}")
        rasa_available = False

    # Standalone classifier as fallback or confidence booster
    standalone_intent, standalone_conf = _classify_intent_standalone(message)

    if intent == "unknown" or intent_confidence < 0.3:
        # Rasa failed or low confidence - use standalone
        if standalone_conf > 0:
            intent = standalone_intent
            intent_confidence = standalone_conf
            logger.info(f"[chat] Using standalone intent: {intent} ({standalone_conf:.2f})")

    emotion_group = _map_emotion_group(expression, compound_emotion)

    # ── Response generation ─────────────────────────────────────────
    rasa_responses = []
    used_standalone = False

    if rasa_available:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
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
            rasa_available = False

    # ── Standalone fallback ─────────────────────────────────────────
    # If Rasa gave no useful response, generate one ourselves
    rasa_has_content = any(r.get("text", "").strip() for r in rasa_responses)

    if not rasa_has_content:
        standalone_response = _generate_standalone_response(
            intent, emotion_group, momentum=momentum
        )
        if standalone_response:
            rasa_responses = [{"text": standalone_response}]
            used_standalone = True
            logger.info(f"[chat] Standalone response for intent={intent} emotion={emotion_group}")
        else:
            # Last resort: acknowledge the message intelligently
            fallback = _generate_fallback_response(message, emotion_group, momentum)
            rasa_responses = [{"text": fallback}]
            used_standalone = True

    # Apply emotion weighting only if we used Rasa's response
    # (standalone responses already have emotion awareness baked in)
    if used_standalone:
        final_responses = rasa_responses
    else:
        final_responses = _apply_emotion_weighting(
            rasa_responses, intent, expression, expression_confidence,
            expression_intensity, compound=compound_emotion, momentum=momentum
        )

    return JSONResponse({
        "responses": final_responses,
        "emotion": emotion_payload,
        "intent": intent,
        "intent_confidence": intent_confidence,
        "sender_id": sender_id,
        "source": "standalone" if used_standalone else "rasa",
    })


@app.get("/stats")
async def stats():
    with cache_lock:
        active_senders = len(signals_cache)
        total_requests = sum(
            1 for s in signals_cache.values()
            if s.get("timestamp", 0) > time.time() - 60
        )

    return JSONResponse({
        "active_senders": active_senders,
        "recent_activity": total_requests,
        "timestamp": time.time()
    })


if __name__ == "__main__":
    port = int(os.getenv("VISION_API_PORT", "8081"))
    host = os.getenv("VISION_API_HOST", "0.0.0.0")

    logger.info(f"Starting Vision API v3.1 on {host}:{port}")
    logger.info(f"Access the web interface at: http://localhost:{port}")
    logger.info(f"Health check: http://localhost:{port}/health")

    uvicorn.run(app, host=host, port=port, log_level="info")
