"""
Advanced Microexpression and Gaze Detection Module v2.0

Uses MediaPipe FaceLandmarker (tasks API) with 52 ARKit blendshapes for
FACS-based emotion classification. Includes:
- Softmax-normalized emotion scoring from blendshape activators/inhibitors
- Exponential Moving Average (EMA) temporal smoothing
- Blendshape-based gaze estimation
- Multi-signal engagement scoring
- Automatic model download on first run
- Haar cascade fallback if MediaPipe unavailable
"""

import os
import cv2
import math
import logging
import urllib.request
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "face_landmarker.task")

# ── FACS-based emotion rules ────────────────────────────────────────────
# Each emotion maps blendshape names -> weights.
# Positive weight = activator, negative weight = inhibitor.
EMOTION_RULES = {
    "happy": {
        "mouthSmileLeft": 1.5, "mouthSmileRight": 1.5,
        "cheekSquintLeft": 0.8, "cheekSquintRight": 0.8,
        "mouthFrownLeft": -1.0, "mouthFrownRight": -1.0,
    },
    "sad": {
        "mouthFrownLeft": 1.5, "mouthFrownRight": 1.5,
        "browInnerUp": 1.0,
        "mouthSmileLeft": -1.0, "mouthSmileRight": -1.0,
    },
    "angry": {
        "browDownLeft": 1.5, "browDownRight": 1.5,
        "jawForward": 0.8,
        "noseSneerLeft": 0.6, "noseSneerRight": 0.6,
        "mouthSmileLeft": -0.5, "mouthSmileRight": -0.5,
    },
    "surprise": {
        "eyeWideLeft": 1.5, "eyeWideRight": 1.5,
        "jawOpen": 1.0,
        "browOuterUpLeft": 1.0, "browOuterUpRight": 1.0,
    },
    "fear": {
        "eyeWideLeft": 1.2, "eyeWideRight": 1.2,
        "browInnerUp": 1.0,
        "mouthStretchLeft": 0.8, "mouthStretchRight": 0.8,
        "mouthSmileLeft": -0.5, "mouthSmileRight": -0.5,
    },
    "disgust": {
        "noseSneerLeft": 1.5, "noseSneerRight": 1.5,
        "mouthFrownLeft": 0.8, "mouthFrownRight": 0.8,
        "mouthUpperUpLeft": 0.6, "mouthUpperUpRight": 0.6,
        "mouthSmileLeft": -0.5, "mouthSmileRight": -0.5,
    },
}

EMOTIONS = list(EMOTION_RULES.keys()) + ["neutral"]


@dataclass
class EmotionResult:
    expression: str = "neutral"
    confidence: float = 0.5
    intensity: float = 0.0
    gaze_state: str = "forward"
    gaze_confidence: float = 0.5
    engagement_level: float = 0.5
    emotion_distribution: Dict[str, float] = field(
        default_factory=lambda: {e: (1.0 if e == "neutral" else 0.0) for e in EMOTIONS}
    )


def _softmax(scores: Dict[str, float]) -> Dict[str, float]:
    """Numerically stable softmax over a dict of scores."""
    vals = np.array(list(scores.values()), dtype=np.float64)
    vals -= vals.max()
    exp_vals = np.exp(vals)
    total = exp_vals.sum()
    if total == 0:
        n = len(scores)
        return {k: 1.0 / n for k in scores}
    return {k: float(v / total) for k, v in zip(scores.keys(), exp_vals)}


def _download_model() -> bool:
    """Download FaceLandmarker model if not present."""
    if os.path.exists(MODEL_PATH):
        return True
    os.makedirs(MODEL_DIR, exist_ok=True)
    logger.info(f"Downloading FaceLandmarker model to {MODEL_PATH} ...")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        logger.info("Model downloaded successfully.")
        return True
    except Exception as e:
        logger.warning(f"Model download failed: {e}")
        return False


class _EmotionSmoother:
    """Exponential Moving Average smoother over emotion distributions."""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self._avg: Optional[Dict[str, float]] = None

    def smooth(self, dist: Dict[str, float]) -> Dict[str, float]:
        if self._avg is None:
            self._avg = dict(dist)
            return dict(dist)
        smoothed = {}
        for k in dist:
            smoothed[k] = self.alpha * dist[k] + (1 - self.alpha) * self._avg.get(k, 0.0)
        self._avg = smoothed
        return smoothed


class _HaarFallbackDetector:
    """Minimal Haar cascade fallback when MediaPipe is unavailable."""

    def __init__(self):
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._smile_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_smile.xml"
        )
        self._eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )

    def detect(self, frame: np.ndarray) -> Dict:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(gray, 1.3, 5)

        if len(faces) == 0:
            return {
                "gaze_state": "away",
                "micro_expression": "neutral",
                "expression_confidence": 0.3,
                "expression_intensity": 0.0,
                "gaze_confidence": 0.3,
                "engagement_level": 0.2,
                "emotion_distribution": {e: (1.0 if e == "neutral" else 0.0) for e in EMOTIONS},
            }

        (x, y, w, h) = faces[0]
        roi_gray = gray[y:y + h, x:x + w]

        smiles = self._smile_cascade.detectMultiScale(roi_gray, 1.8, 20)
        eyes = self._eye_cascade.detectMultiScale(roi_gray, 1.1, 5)

        expr = "happy" if len(smiles) > 0 else "neutral"
        intensity = 0.6 if len(smiles) > 0 else 0.0
        confidence = 0.55

        # Gaze from face center offset
        frame_cx = frame.shape[1] / 2
        face_cx = x + w / 2
        offset = (face_cx - frame_cx) / frame.shape[1]
        if abs(offset) < 0.1:
            gaze = "forward"
        elif offset < 0:
            gaze = "left"
        else:
            gaze = "right"

        engagement = 0.6 if len(eyes) >= 2 else 0.3

        dist = {e: 0.0 for e in EMOTIONS}
        dist[expr] = 0.7
        dist["neutral"] = 0.3 if expr != "neutral" else 1.0

        return {
            "gaze_state": gaze,
            "micro_expression": expr,
            "expression_confidence": confidence,
            "expression_intensity": intensity,
            "gaze_confidence": 0.4,
            "engagement_level": engagement,
            "emotion_distribution": dist,
        }


class MicroexpressionDetector:
    """
    Advanced detector using MediaPipe FaceLandmarker with 52 blendshapes
    for FACS-based emotion classification.

    Falls back to Haar cascades if MediaPipe is unavailable.
    """

    def __init__(self):
        self._smoother = _EmotionSmoother(alpha=0.3)
        self._landmarker = None
        self._fallback = None
        self._use_fallback = False
        self._last = EmotionResult()
        self._init_detector()

    def _init_detector(self):
        """Try to initialise MediaPipe FaceLandmarker, fall back to Haar."""
        if not _download_model():
            logger.warning("Using Haar cascade fallback.")
            self._fallback = _HaarFallbackDetector()
            self._use_fallback = True
            return

        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import (
                FaceLandmarker,
                FaceLandmarkerOptions,
                RunningMode,
            )

            options = FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=RunningMode.IMAGE,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=False,
                num_faces=1,
            )
            self._landmarker = FaceLandmarker.create_from_options(options)
            logger.info("MediaPipe FaceLandmarker initialized successfully.")
        except Exception as e:
            logger.warning(f"MediaPipe init failed ({e}), using Haar fallback.")
            self._fallback = _HaarFallbackDetector()
            self._use_fallback = True

    # ── FACS classification ─────────────────────────────────────────────

    def _facs_classify(self, blendshapes: Dict[str, float]) -> Dict[str, float]:
        """Score emotions from blendshape values using FACS rules + softmax."""
        raw_scores: Dict[str, float] = {}
        for emotion, rules in EMOTION_RULES.items():
            score = 0.0
            for bs_name, weight in rules.items():
                val = blendshapes.get(bs_name, 0.0)
                score += weight * val
            raw_scores[emotion] = max(0.0, score)

        # Neutral = inverse of total activation
        total_act = sum(raw_scores.values())
        raw_scores["neutral"] = max(0.0, 1.0 - total_act * 0.5)

        return _softmax(raw_scores)

    # ── Blendshape gaze ─────────────────────────────────────────────────

    def _blendshape_gaze(self, bs: Dict[str, float]) -> tuple:
        """Estimate gaze direction from eye-look blendshapes."""
        look_left = (bs.get("eyeLookOutLeft", 0) + bs.get("eyeLookInRight", 0)) / 2
        look_right = (bs.get("eyeLookInLeft", 0) + bs.get("eyeLookOutRight", 0)) / 2
        look_up = (bs.get("eyeLookUpLeft", 0) + bs.get("eyeLookUpRight", 0)) / 2
        look_down = (bs.get("eyeLookDownLeft", 0) + bs.get("eyeLookDownRight", 0)) / 2

        horiz = look_right - look_left
        vert = look_down - look_up

        H_THRESH = 0.15
        V_THRESH = 0.15

        if abs(horiz) < H_THRESH and abs(vert) < V_THRESH:
            gaze = "forward"
        elif vert > V_THRESH:
            gaze = "down"
        elif vert < -V_THRESH:
            gaze = "up"
        elif horiz > H_THRESH:
            gaze = "right"
        else:
            gaze = "left"

        magnitude = math.sqrt(horiz ** 2 + vert ** 2)
        confidence = min(1.0, 0.5 + magnitude * 2)
        return gaze, confidence

    # ── Engagement ──────────────────────────────────────────────────────

    def _compute_engagement(self, gaze: str, gaze_conf: float,
                            intensity: float, bs: Dict[str, float]) -> float:
        """Multi-signal engagement scoring."""
        score = 0.5

        # Gaze contribution
        if gaze == "forward":
            score += 0.2 * gaze_conf
        elif gaze in ("away", "down"):
            score -= 0.25 * gaze_conf
        else:
            score -= 0.1 * gaze_conf

        # Expression intensity
        score += 0.15 * intensity

        # Facial activity (blink, jaw)
        activity = (
            bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0) +
            bs.get("jawOpen", 0)
        ) / 3.0
        score += 0.1 * activity

        return max(0.0, min(1.0, score))

    # ── Main detect ─────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray) -> Dict:
        """
        Detect emotion, gaze, and engagement from a BGR frame.

        Returns dict with: gaze_state, micro_expression, expression_confidence,
        expression_intensity, gaze_confidence, engagement_level, emotion_distribution
        """
        if frame is None or frame.size == 0:
            return self._as_dict(self._last)

        if self._use_fallback:
            result = self._fallback.detect(frame)
            result["emotion_distribution"] = self._smoother.smooth(
                result.get("emotion_distribution", {e: 0.0 for e in EMOTIONS})
            )
            return result

        try:
            import mediapipe as mp

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect(mp_image)

            if not result.face_blendshapes or len(result.face_blendshapes) == 0:
                return {
                    "gaze_state": "away",
                    "micro_expression": "neutral",
                    "expression_confidence": 0.3,
                    "expression_intensity": 0.0,
                    "gaze_confidence": 0.3,
                    "engagement_level": 0.2,
                    "emotion_distribution": self._smoother.smooth(
                        {e: (1.0 if e == "neutral" else 0.0) for e in EMOTIONS}
                    ),
                }

            # Extract blendshapes as dict
            bs: Dict[str, float] = {}
            for category in result.face_blendshapes[0]:
                bs[category.category_name] = category.score

            # FACS classify
            raw_dist = self._facs_classify(bs)
            smoothed_dist = self._smoother.smooth(raw_dist)

            # Best emotion
            best_emotion = max(smoothed_dist, key=smoothed_dist.get)

            # Confidence = gap between top-1 and top-2
            sorted_probs = sorted(smoothed_dist.values(), reverse=True)
            confidence = min(1.0, 0.5 + (sorted_probs[0] - sorted_probs[1]) * 2) if len(sorted_probs) > 1 else 0.5

            # Intensity = how non-neutral the distribution is
            intensity = 1.0 - smoothed_dist.get("neutral", 0.0)
            intensity = max(0.0, min(1.0, intensity))

            # Gaze
            gaze, gaze_conf = self._blendshape_gaze(bs)

            # Engagement
            engagement = self._compute_engagement(gaze, gaze_conf, intensity, bs)

            self._last = EmotionResult(
                expression=best_emotion,
                confidence=confidence,
                intensity=intensity,
                gaze_state=gaze,
                gaze_confidence=gaze_conf,
                engagement_level=engagement,
                emotion_distribution=smoothed_dist,
            )

            return self._as_dict(self._last)

        except Exception as e:
            logger.error(f"Detection error: {e}", exc_info=True)
            return self._as_dict(self._last)

    def _as_dict(self, r: EmotionResult) -> Dict:
        return {
            "gaze_state": r.gaze_state,
            "micro_expression": r.expression,
            "expression_confidence": float(r.confidence),
            "expression_intensity": float(r.intensity),
            "gaze_confidence": float(r.gaze_confidence),
            "engagement_level": float(r.engagement_level),
            "emotion_distribution": dict(r.emotion_distribution),
        }

    def __del__(self):
        if self._landmarker:
            try:
                self._landmarker.close()
            except Exception:
                pass
