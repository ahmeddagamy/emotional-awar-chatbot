"""
Advanced Microexpression and Gaze Detection Module v3.0

Uses MediaPipe FaceLandmarker (tasks API) with 52 ARKit blendshapes for
FACS-based emotion classification. Includes:
- Extended FACS rules with calibrated activator/inhibitor weights
- Compound emotion detection (e.g. happily surprised, anxious disgust)
- Micro-expression spike detection (brief emotion flashes)
- Adaptive EMA smoothing (fast attack, slow decay)
- Head pose estimation from 3D face landmarks
- Bayesian-calibrated confidence scoring
- Multi-signal engagement with nod/tilt/blink detection
- Automatic model download on first run
- Haar cascade fallback if MediaPipe unavailable
"""

import os
import cv2
import math
import logging
import urllib.request
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "face_landmarker.task")

# ── Extended FACS-based emotion rules ────────────────────────────────────
# Each emotion maps blendshape names -> weights.
# Positive weight = activator, negative weight = inhibitor.
# Weights calibrated against ARKit blendshape activation ranges.
EMOTION_RULES = {
    "happy": {
        # AU6 (cheek raiser) + AU12 (lip corner puller) = Duchenne smile
        "mouthSmileLeft": 1.8, "mouthSmileRight": 1.8,
        "cheekSquintLeft": 1.2, "cheekSquintRight": 1.2,
        # AU25 lips part (secondary)
        "mouthClose": -0.4,
        # Inhibitors
        "mouthFrownLeft": -1.2, "mouthFrownRight": -1.2,
        "browDownLeft": -0.6, "browDownRight": -0.6,
        "noseSneerLeft": -0.3, "noseSneerRight": -0.3,
    },
    "sad": {
        # AU1 (inner brow raise) + AU15 (lip corner depressor) + AU17 (chin raiser)
        "mouthFrownLeft": 1.6, "mouthFrownRight": 1.6,
        "browInnerUp": 1.2,
        "mouthPucker": 0.4,  # lip tightening
        "mouthLowerDownLeft": 0.3, "mouthLowerDownRight": 0.3,
        # Inhibitors
        "mouthSmileLeft": -1.2, "mouthSmileRight": -1.2,
        "cheekSquintLeft": -0.5, "cheekSquintRight": -0.5,
        "eyeWideLeft": -0.3, "eyeWideRight": -0.3,
    },
    "angry": {
        # AU4 (brow lowerer) + AU5 upper lid + AU23 (lip tightener) + AU24 (lip presser)
        "browDownLeft": 1.8, "browDownRight": 1.8,
        "jawForward": 0.9,
        "noseSneerLeft": 0.8, "noseSneerRight": 0.8,
        "mouthPressLeft": 0.6, "mouthPressRight": 0.6,
        "eyeSquintLeft": 0.4, "eyeSquintRight": 0.4,
        # Inhibitors
        "mouthSmileLeft": -0.8, "mouthSmileRight": -0.8,
        "browInnerUp": -0.5,
        "eyeWideLeft": -0.3, "eyeWideRight": -0.3,
    },
    "surprise": {
        # AU1+AU2 (brow raise) + AU5 (upper lid raise) + AU26 (jaw drop)
        "eyeWideLeft": 1.8, "eyeWideRight": 1.8,
        "jawOpen": 1.2,
        "browOuterUpLeft": 1.3, "browOuterUpRight": 1.3,
        "browInnerUp": 1.0,
        # Inhibitors
        "browDownLeft": -1.0, "browDownRight": -1.0,
        "eyeSquintLeft": -0.6, "eyeSquintRight": -0.6,
        "mouthFrownLeft": -0.3, "mouthFrownRight": -0.3,
    },
    "fear": {
        # AU1+AU2 (brow raise) + AU4 (brow lowerer) + AU5 (upper lid) + AU20 (lip stretch)
        "eyeWideLeft": 1.4, "eyeWideRight": 1.4,
        "browInnerUp": 1.2,
        "browOuterUpLeft": 0.6, "browOuterUpRight": 0.6,
        "mouthStretchLeft": 1.0, "mouthStretchRight": 1.0,
        "mouthClose": -0.3,
        # Fear-specific: slight brow lower combined with raise (AU1+AU4)
        "browDownLeft": 0.3, "browDownRight": 0.3,
        # Inhibitors
        "mouthSmileLeft": -0.8, "mouthSmileRight": -0.8,
        "cheekSquintLeft": -0.4, "cheekSquintRight": -0.4,
    },
    "disgust": {
        # AU9 (nose wrinkler) + AU10 (upper lip raiser) + AU17 (chin raiser)
        "noseSneerLeft": 1.8, "noseSneerRight": 1.8,
        "mouthFrownLeft": 0.6, "mouthFrownRight": 0.6,
        "mouthUpperUpLeft": 1.0, "mouthUpperUpRight": 1.0,
        "mouthShrugUpper": 0.5,
        "cheekPuff": 0.3,
        # Inhibitors
        "mouthSmileLeft": -0.8, "mouthSmileRight": -0.8,
        "eyeWideLeft": -0.3, "eyeWideRight": -0.3,
        "browInnerUp": -0.3,
    },
    "contempt": {
        # AU12L or AU12R (unilateral lip corner pull) + AU14 (dimpler)
        "mouthSmileLeft": 0.8, "mouthSmileRight": -0.3,  # asymmetric
        "mouthDimpleLeft": 0.6, "mouthDimpleRight": 0.3,
        "mouthPressLeft": 0.4,
        "noseSneerLeft": 0.3,
        # Inhibitors
        "jawOpen": -0.5,
        "eyeWideLeft": -0.3, "eyeWideRight": -0.3,
    },
}

# Compound emotion rules - detected when two base emotions co-activate
COMPOUND_RULES = {
    "anxious": {  # fear + sad
        "primary": "fear",
        "secondary": "sad",
        "min_primary": 0.15,
        "min_secondary": 0.10,
        "label": "anxious",
    },
    "happily_surprised": {
        "primary": "surprise",
        "secondary": "happy",
        "min_primary": 0.15,
        "min_secondary": 0.12,
        "label": "happily_surprised",
    },
    "frustrated": {  # angry + sad
        "primary": "angry",
        "secondary": "sad",
        "min_primary": 0.12,
        "min_secondary": 0.10,
        "label": "frustrated",
    },
    "nervous_disgust": {  # fear + disgust
        "primary": "fear",
        "secondary": "disgust",
        "min_primary": 0.12,
        "min_secondary": 0.10,
        "label": "nervous_disgust",
    },
    "bittersweet": {  # happy + sad
        "primary": "happy",
        "secondary": "sad",
        "min_primary": 0.12,
        "min_secondary": 0.10,
        "label": "bittersweet",
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
    compound_emotion: Optional[str] = None
    compound_confidence: float = 0.0
    micro_expression_spike: Optional[str] = None
    spike_intensity: float = 0.0
    head_pitch: float = 0.0
    head_yaw: float = 0.0
    head_roll: float = 0.0
    valence: float = 0.0  # -1 (negative) to +1 (positive)
    arousal: float = 0.0  # 0 (calm) to 1 (excited)


def _softmax(scores: Dict[str, float], temperature: float = 1.0) -> Dict[str, float]:
    """Numerically stable softmax with temperature control."""
    vals = np.array(list(scores.values()), dtype=np.float64)
    vals = vals / max(temperature, 0.01)
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


class _AdaptiveSmoother:
    """
    Adaptive EMA smoother: fast attack on emotion changes, slow decay.

    When a new emotion spikes above threshold, smoothing alpha increases
    to respond quickly. During steady state, alpha decreases for stability.
    """

    def __init__(self, base_alpha: float = 0.25, spike_alpha: float = 0.6,
                 spike_threshold: float = 0.15):
        self.base_alpha = base_alpha
        self.spike_alpha = spike_alpha
        self.spike_threshold = spike_threshold
        self._avg: Optional[Dict[str, float]] = None

    def smooth(self, dist: Dict[str, float]) -> Dict[str, float]:
        if self._avg is None:
            self._avg = dict(dist)
            return dict(dist)

        # Detect spike: max change from previous frame
        max_delta = max(abs(dist.get(k, 0) - self._avg.get(k, 0)) for k in dist)
        alpha = self.spike_alpha if max_delta > self.spike_threshold else self.base_alpha

        smoothed = {}
        for k in dist:
            smoothed[k] = alpha * dist[k] + (1 - alpha) * self._avg.get(k, 0.0)
        self._avg = smoothed
        return smoothed


class _MicroExpressionDetector:
    """
    Detects brief emotion spikes (micro-expressions) that appear for 1-3 frames
    then disappear. These are involuntary and often reveal true emotion.
    """

    def __init__(self, window_size: int = 8, spike_threshold: float = 0.20,
                 decay_threshold: float = 0.08):
        self.window_size = window_size
        self.spike_threshold = spike_threshold
        self.decay_threshold = decay_threshold
        self._history: deque = deque(maxlen=window_size)
        self._baseline: Optional[Dict[str, float]] = None
        self._baseline_alpha = 0.05  # slow baseline update

    def update(self, dist: Dict[str, float]) -> Tuple[Optional[str], float]:
        """Returns (spike_emotion, spike_intensity) or (None, 0.0)."""
        self._history.append(dict(dist))

        # Build baseline from slow EMA
        if self._baseline is None:
            self._baseline = dict(dist)
            return None, 0.0

        for k in dist:
            self._baseline[k] = (
                self._baseline_alpha * dist[k] +
                (1 - self._baseline_alpha) * self._baseline.get(k, 0.0)
            )

        if len(self._history) < 3:
            return None, 0.0

        # Check for spike pattern: low -> high -> low
        current = self._history[-1]
        prev = self._history[-2]
        prev2 = self._history[-3] if len(self._history) >= 3 else prev

        best_spike = None
        best_intensity = 0.0

        for emotion in dist:
            if emotion == "neutral":
                continue
            curr_val = current.get(emotion, 0)
            prev_val = prev.get(emotion, 0)
            prev2_val = prev2.get(emotion, 0)
            baseline_val = self._baseline.get(emotion, 0)

            # Spike: previous frame was significantly above baseline AND
            # current frame is dropping back down
            spike_height = prev_val - baseline_val
            is_rising = prev_val > prev2_val + self.decay_threshold
            is_falling = curr_val < prev_val - self.decay_threshold

            if spike_height > self.spike_threshold and (is_rising or is_falling):
                if spike_height > best_intensity:
                    best_spike = emotion
                    best_intensity = spike_height

        return best_spike, best_intensity


class _HeadPoseEstimator:
    """
    Estimates head pitch/yaw/roll from MediaPipe face landmarks.
    Uses key landmark positions relative to face bounding geometry.
    """

    # Key landmark indices (MediaPipe 468 face mesh)
    NOSE_TIP = 1
    CHIN = 152
    LEFT_EYE_OUTER = 33
    RIGHT_EYE_OUTER = 263
    LEFT_MOUTH = 61
    RIGHT_MOUTH = 291
    FOREHEAD = 10

    def estimate(self, landmarks) -> Tuple[float, float, float]:
        """Returns (pitch, yaw, roll) in degrees from face landmarks."""
        if not landmarks or len(landmarks) < 300:
            return 0.0, 0.0, 0.0

        try:
            nose = landmarks[self.NOSE_TIP]
            chin = landmarks[self.CHIN]
            left_eye = landmarks[self.LEFT_EYE_OUTER]
            right_eye = landmarks[self.RIGHT_EYE_OUTER]
            forehead = landmarks[self.FOREHEAD]
            left_mouth = landmarks[self.LEFT_MOUTH]
            right_mouth = landmarks[self.RIGHT_MOUTH]

            # Yaw: horizontal nose offset from eye midpoint
            eye_mid_x = (left_eye.x + right_eye.x) / 2
            yaw = math.degrees(math.atan2(nose.x - eye_mid_x, 0.5)) * 2

            # Pitch: vertical nose position relative to forehead-chin line
            pitch = 0.0
            face_height = abs(chin.y - forehead.y)
            if face_height > 0.01:
                nose_ratio = (nose.y - forehead.y) / face_height
                pitch = (nose_ratio - 0.45) * 90  # 0.45 = neutral position

            # Roll: eye line angle
            dx = right_eye.x - left_eye.x
            dy = right_eye.y - left_eye.y
            roll = math.degrees(math.atan2(dy, dx))

            return (
                max(-45, min(45, pitch)),
                max(-45, min(45, yaw)),
                max(-30, min(30, roll))
            )
        except (IndexError, AttributeError):
            return 0.0, 0.0, 0.0


class _EngagementAnalyzer:
    """
    Multi-signal engagement scoring with temporal awareness.
    Tracks blink rate, head movement, gaze stability, expression activity.
    """

    def __init__(self, history_size: int = 30):
        self._blink_history: deque = deque(maxlen=history_size)
        self._gaze_history: deque = deque(maxlen=history_size)
        self._head_movement: deque = deque(maxlen=history_size)
        self._last_pitch = 0.0
        self._last_yaw = 0.0
        self._nod_count = 0
        self._nod_cooldown = 0

    def compute(self, gaze: str, gaze_conf: float, intensity: float,
                bs: Dict[str, float], pitch: float, yaw: float) -> float:
        """Multi-signal engagement score [0, 1]."""
        score = 0.0
        weights_total = 0.0

        # 1. Gaze direction (weight: 0.30)
        w_gaze = 0.30
        if gaze == "forward":
            gaze_score = 0.9 * gaze_conf
        elif gaze in ("up",):
            gaze_score = 0.5 * gaze_conf  # might be thinking
        elif gaze in ("left", "right"):
            gaze_score = 0.3 * gaze_conf
        else:  # down, away
            gaze_score = 0.1 * gaze_conf
        score += w_gaze * gaze_score
        weights_total += w_gaze
        self._gaze_history.append(gaze == "forward")

        # 2. Expression activity (weight: 0.20)
        w_expr = 0.20
        score += w_expr * min(1.0, intensity * 1.2)
        weights_total += w_expr

        # 3. Eye openness (weight: 0.15)
        w_eyes = 0.15
        blink_l = bs.get("eyeBlinkLeft", 0)
        blink_r = bs.get("eyeBlinkRight", 0)
        avg_blink = (blink_l + blink_r) / 2
        self._blink_history.append(avg_blink > 0.5)

        # Eyes open = engaged; sustained closed = disengaged
        if avg_blink < 0.3:
            eye_score = 0.8
        elif avg_blink < 0.6:
            eye_score = 0.5
        else:
            eye_score = 0.2
        score += w_eyes * eye_score
        weights_total += w_eyes

        # 4. Head nodding detection (weight: 0.15)
        w_nod = 0.15
        pitch_delta = pitch - self._last_pitch
        yaw_delta = yaw - self._last_yaw
        self._head_movement.append(abs(pitch_delta) + abs(yaw_delta))

        # Detect nod: pitch oscillation
        if self._nod_cooldown > 0:
            self._nod_cooldown -= 1
        if abs(pitch_delta) > 2.0 and self._nod_cooldown == 0:
            self._nod_count += 1
            self._nod_cooldown = 5  # frames cooldown

        nod_score = min(1.0, self._nod_count * 0.2)
        # Decay nod count slowly
        if len(self._head_movement) > 10 and self._nod_count > 0:
            self._nod_count = max(0, self._nod_count - 0.05)
        score += w_nod * nod_score
        weights_total += w_nod

        self._last_pitch = pitch
        self._last_yaw = yaw

        # 5. Head orientation toward camera (weight: 0.10)
        w_orient = 0.10
        # Closer to 0 yaw/pitch = more engaged
        orient_score = max(0, 1.0 - (abs(yaw) + abs(pitch)) / 45.0)
        score += w_orient * orient_score
        weights_total += w_orient

        # 6. Gaze stability (weight: 0.10) - consistent forward gaze
        w_stability = 0.10
        if len(self._gaze_history) >= 5:
            recent_forward = sum(1 for g in list(self._gaze_history)[-5:] if g)
            stability_score = recent_forward / 5.0
        else:
            stability_score = 0.5
        score += w_stability * stability_score
        weights_total += w_stability

        return max(0.0, min(1.0, score / weights_total if weights_total > 0 else 0.5))


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
                "compound_emotion": None,
                "compound_confidence": 0.0,
                "micro_expression_spike": None,
                "spike_intensity": 0.0,
                "head_pitch": 0.0,
                "head_yaw": 0.0,
                "head_roll": 0.0,
                "valence": 0.0,
                "arousal": 0.0,
            }

        (x, y, w, h) = faces[0]
        roi_gray = gray[y:y + h, x:x + w]

        smiles = self._smile_cascade.detectMultiScale(roi_gray, 1.8, 20)
        eyes = self._eye_cascade.detectMultiScale(roi_gray, 1.1, 5)

        expr = "happy" if len(smiles) > 0 else "neutral"
        intensity = 0.6 if len(smiles) > 0 else 0.0
        confidence = 0.55

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
            "compound_emotion": None,
            "compound_confidence": 0.0,
            "micro_expression_spike": None,
            "spike_intensity": 0.0,
            "head_pitch": 0.0,
            "head_yaw": 0.0,
            "head_roll": 0.0,
            "valence": 0.3 if expr == "happy" else 0.0,
            "arousal": 0.3 if expr == "happy" else 0.1,
        }


# ── Valence/Arousal mapping ─────────────────────────────────────────────
VALENCE_MAP = {
    "happy": 0.8, "surprise": 0.3, "contempt": -0.2,
    "neutral": 0.0, "sad": -0.7, "angry": -0.6,
    "fear": -0.5, "disgust": -0.6,
}
AROUSAL_MAP = {
    "happy": 0.5, "surprise": 0.9, "contempt": 0.2,
    "neutral": 0.1, "sad": 0.3, "angry": 0.8,
    "fear": 0.8, "disgust": 0.5,
}


class MicroexpressionDetector:
    """
    Advanced detector v3.0 using MediaPipe FaceLandmarker with 52 blendshapes.

    Features:
    - Extended FACS rules with calibrated weights
    - Compound emotion detection
    - Micro-expression spike detection
    - Adaptive temporal smoothing
    - Head pose estimation (pitch/yaw/roll)
    - Bayesian confidence calibration
    - Multi-signal engagement with nod detection
    - Valence/arousal dimensional emotion model
    """

    def __init__(self):
        self._smoother = _AdaptiveSmoother(base_alpha=0.25, spike_alpha=0.6)
        self._spike_detector = _MicroExpressionDetector()
        self._head_pose = _HeadPoseEstimator()
        self._engagement = _EngagementAnalyzer()
        self._landmarker = None
        self._fallback = None
        self._use_fallback = False
        self._last = EmotionResult()
        self._frame_count = 0
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
                output_facial_transformation_matrixes=True,
                num_faces=1,
            )
            self._landmarker = FaceLandmarker.create_from_options(options)
            logger.info("MediaPipe FaceLandmarker v3.0 initialized successfully.")
        except Exception as e:
            logger.warning(f"MediaPipe init failed ({e}), using Haar fallback.")
            self._fallback = _HaarFallbackDetector()
            self._use_fallback = True

    # ── FACS classification ─────────────────────────────────────────────

    def _facs_classify(self, blendshapes: Dict[str, float]) -> Dict[str, float]:
        """Score emotions from blendshape values using extended FACS rules."""
        raw_scores: Dict[str, float] = {}
        for emotion, rules in EMOTION_RULES.items():
            score = 0.0
            activator_sum = 0.0
            inhibitor_sum = 0.0
            for bs_name, weight in rules.items():
                val = blendshapes.get(bs_name, 0.0)
                contribution = weight * val
                if weight > 0:
                    activator_sum += contribution
                else:
                    inhibitor_sum += contribution  # negative
                score += contribution

            # Apply non-linear scaling: stronger activations count more
            if activator_sum > 0:
                score = activator_sum ** 0.85 + inhibitor_sum
            raw_scores[emotion] = max(0.0, score)

        # Neutral = inverse of total activation with diminishing returns
        total_act = sum(raw_scores.values())
        raw_scores["neutral"] = max(0.0, 1.0 / (1.0 + total_act * 1.5))

        # Temperature-scaled softmax for sharper peaks
        temperature = 0.8 if total_act > 0.5 else 1.2
        return _softmax(raw_scores, temperature=temperature)

    # ── Compound emotion detection ─────────────────────────────────────

    def _detect_compound(self, dist: Dict[str, float]) -> Tuple[Optional[str], float]:
        """Detect compound emotions from co-activated base emotions."""
        best_compound = None
        best_confidence = 0.0

        for name, rule in COMPOUND_RULES.items():
            primary_val = dist.get(rule["primary"], 0)
            secondary_val = dist.get(rule["secondary"], 0)

            if (primary_val >= rule["min_primary"] and
                    secondary_val >= rule["min_secondary"]):
                # Confidence based on geometric mean of both
                conf = math.sqrt(primary_val * secondary_val)
                if conf > best_confidence:
                    best_compound = rule["label"]
                    best_confidence = conf

        return best_compound, best_confidence

    # ── Blendshape gaze ─────────────────────────────────────────────────

    def _blendshape_gaze(self, bs: Dict[str, float]) -> Tuple[str, float]:
        """Estimate gaze direction from eye-look blendshapes with improved thresholds."""
        look_left = (bs.get("eyeLookOutLeft", 0) + bs.get("eyeLookInRight", 0)) / 2
        look_right = (bs.get("eyeLookInLeft", 0) + bs.get("eyeLookOutRight", 0)) / 2
        look_up = (bs.get("eyeLookUpLeft", 0) + bs.get("eyeLookUpRight", 0)) / 2
        look_down = (bs.get("eyeLookDownLeft", 0) + bs.get("eyeLookDownRight", 0)) / 2

        horiz = look_right - look_left
        vert = look_down - look_up

        # Adaptive thresholds based on eye openness
        eye_open = 1.0 - (bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2
        h_thresh = 0.12 * max(0.5, eye_open)
        v_thresh = 0.12 * max(0.5, eye_open)

        if abs(horiz) < h_thresh and abs(vert) < v_thresh:
            gaze = "forward"
        elif vert > v_thresh and abs(vert) > abs(horiz):
            gaze = "down"
        elif vert < -v_thresh and abs(vert) > abs(horiz):
            gaze = "up"
        elif horiz > h_thresh:
            gaze = "right"
        else:
            gaze = "left"

        magnitude = math.sqrt(horiz ** 2 + vert ** 2)
        confidence = min(1.0, 0.4 + magnitude * 3)
        return gaze, confidence

    # ── Confidence calibration ──────────────────────────────────────────

    def _calibrate_confidence(self, dist: Dict[str, float],
                              bs: Dict[str, float]) -> float:
        """
        Bayesian-inspired confidence calibration.
        Considers: distribution entropy, top-1/top-2 gap, face quality signals.
        """
        sorted_probs = sorted(dist.values(), reverse=True)

        # 1. Top-1 vs top-2 gap
        if len(sorted_probs) > 1:
            gap = sorted_probs[0] - sorted_probs[1]
        else:
            gap = 0.0

        # 2. Distribution entropy (lower = more confident)
        entropy = 0.0
        for p in dist.values():
            if p > 1e-8:
                entropy -= p * math.log(p + 1e-10)
        max_entropy = math.log(len(dist))
        norm_entropy = entropy / max_entropy if max_entropy > 0 else 0.5

        # 3. Face quality: are eyes visible? (proxy for good detection)
        eye_quality = 1.0 - (bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2

        # 4. Facial activity level (more activity = more signal)
        activity = sum(v for k, v in bs.items() if v > 0.05) / max(1, len(bs))

        # Combine signals
        confidence = (
            0.35 * min(1.0, gap * 3) +         # gap contribution
            0.25 * (1.0 - norm_entropy) +        # entropy contribution
            0.20 * eye_quality +                  # face quality
            0.20 * min(1.0, activity * 5)         # activity level
        )

        return max(0.1, min(0.99, confidence))

    # ── Valence/Arousal computation ─────────────────────────────────────

    def _compute_valence_arousal(self, dist: Dict[str, float]) -> Tuple[float, float]:
        """Compute dimensional emotion values from distribution."""
        valence = sum(dist.get(e, 0) * VALENCE_MAP.get(e, 0) for e in dist)
        arousal = sum(dist.get(e, 0) * AROUSAL_MAP.get(e, 0) for e in dist)
        return (
            max(-1.0, min(1.0, valence)),
            max(0.0, min(1.0, arousal))
        )

    # ── Main detect ─────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray) -> Dict:
        """
        Detect emotion, gaze, engagement, compound emotions, and micro-expression
        spikes from a BGR frame.
        """
        if frame is None or frame.size == 0:
            return self._as_dict(self._last)

        self._frame_count += 1

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
                no_face = EmotionResult(
                    expression="neutral", confidence=0.3, intensity=0.0,
                    gaze_state="away", gaze_confidence=0.3, engagement_level=0.15,
                    emotion_distribution=self._smoother.smooth(
                        {e: (1.0 if e == "neutral" else 0.0) for e in EMOTIONS}
                    ),
                )
                return self._as_dict(no_face)

            # Extract blendshapes
            bs: Dict[str, float] = {}
            for category in result.face_blendshapes[0]:
                bs[category.category_name] = category.score

            # FACS classify
            raw_dist = self._facs_classify(bs)
            smoothed_dist = self._smoother.smooth(raw_dist)

            # Best emotion
            best_emotion = max(smoothed_dist, key=smoothed_dist.get)

            # Calibrated confidence
            confidence = self._calibrate_confidence(smoothed_dist, bs)

            # Intensity
            intensity = 1.0 - smoothed_dist.get("neutral", 0.0)
            intensity = max(0.0, min(1.0, intensity))

            # Compound emotion detection
            compound, compound_conf = self._detect_compound(smoothed_dist)

            # Micro-expression spike detection
            spike_emotion, spike_intensity = self._spike_detector.update(raw_dist)

            # Gaze from blendshapes
            gaze, gaze_conf = self._blendshape_gaze(bs)

            # Head pose from landmarks
            pitch, yaw, roll = 0.0, 0.0, 0.0
            if result.face_landmarks and len(result.face_landmarks) > 0:
                pitch, yaw, roll = self._head_pose.estimate(
                    result.face_landmarks[0]
                )
                # Combine head pose with blendshape gaze for better accuracy
                if abs(yaw) > 15 and gaze == "forward":
                    gaze = "right" if yaw > 0 else "left"
                    gaze_conf = min(1.0, gaze_conf + 0.2)
                if pitch > 15 and gaze == "forward":
                    gaze = "down"
                    gaze_conf = min(1.0, gaze_conf + 0.15)
                elif pitch < -15 and gaze == "forward":
                    gaze = "up"
                    gaze_conf = min(1.0, gaze_conf + 0.15)

            # Multi-signal engagement
            engagement = self._engagement.compute(
                gaze, gaze_conf, intensity, bs, pitch, yaw
            )

            # Valence / Arousal
            valence, arousal = self._compute_valence_arousal(smoothed_dist)

            self._last = EmotionResult(
                expression=best_emotion,
                confidence=confidence,
                intensity=intensity,
                gaze_state=gaze,
                gaze_confidence=gaze_conf,
                engagement_level=engagement,
                emotion_distribution=smoothed_dist,
                compound_emotion=compound,
                compound_confidence=compound_conf,
                micro_expression_spike=spike_emotion,
                spike_intensity=spike_intensity,
                head_pitch=pitch,
                head_yaw=yaw,
                head_roll=roll,
                valence=valence,
                arousal=arousal,
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
            "compound_emotion": r.compound_emotion,
            "compound_confidence": float(r.compound_confidence),
            "micro_expression_spike": r.micro_expression_spike,
            "spike_intensity": float(r.spike_intensity),
            "head_pitch": float(r.head_pitch),
            "head_yaw": float(r.head_yaw),
            "head_roll": float(r.head_roll),
            "valence": float(r.valence),
            "arousal": float(r.arousal),
        }

    def __del__(self):
        if self._landmarker:
            try:
                self._landmarker.close()
            except Exception:
                pass
