"""
Advanced Microexpression and Gaze Detection Module

This module provides highly accurate real-time facial expression analysis and gaze direction 
detection using MediaPipe and advanced computer vision algorithms. Includes confidence scoring
and emotion intensity weighting for emotionally-aware responses.
"""

import cv2
import numpy as np
import mediapipe as mp
from typing import Dict, Optional, Tuple, List
import logging
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EmotionResult:
    """Structured emotion detection result with confidence and intensity."""
    expression: str
    confidence: float  # 0.0 to 1.0
    intensity: float    # 0.0 to 1.0 (how strong the emotion is)
    gaze_state: str
    gaze_confidence: float
    engagement_level: float  # 0.0 to 1.0 (how engaged the user is)


class MicroexpressionDetector:
    """
    Advanced detector for micro-expressions and gaze direction with confidence scoring.
    
    Features:
    - Multi-frame temporal smoothing for stability
    - Confidence scoring for all detections
    - Emotion intensity calculation
    - Engagement level estimation
    - Advanced facial action unit analysis
    """
    
    def __init__(self, smoothing_window: int = 5):
        """
        Initialize the detector with MediaPipe models.
        
        Args:
            smoothing_window: Number of frames to use for temporal smoothing
        """
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        # Temporal smoothing buffers
        self.smoothing_window = smoothing_window
        self.expression_history = deque(maxlen=smoothing_window)
        self.gaze_history = deque(maxlen=smoothing_window)
        self.confidence_history = deque(maxlen=smoothing_window)
        
        # Facial landmark indices (MediaPipe Face Mesh 468 landmarks)
        # Eye landmarks for EAR calculation
        self.LEFT_EYE_INDICES = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
        self.RIGHT_EYE_INDICES = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
        
        # Mouth landmarks
        self.MOUTH_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 320, 307, 375, 321, 308, 324, 318]
        self.MOUTH_INNER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324]
        
        # Eyebrow landmarks
        self.LEFT_EYEBROW = [70, 63, 105, 66, 107]
        self.RIGHT_EYEBROW = [336, 296, 334, 293, 300]
        
        # Key points for gaze and expression
        self.LEFT_EYE_CENTER = 468
        self.RIGHT_EYE_CENTER = 473
        self.NOSE_TIP = 4
        self.NOSE_BRIDGE = 6
        self.CHIN = 18
        
        # Baseline values for normalization (will be calibrated)
        self.baseline_ear = 0.25
        self.baseline_mar = 0.20
        self.baseline_face_size = None
        
        self.last_result = EmotionResult(
            expression="neutral",
            confidence=0.5,
            intensity=0.0,
            gaze_state="forward",
            gaze_confidence=0.5,
            engagement_level=0.5
        )
        
    def _get_landmark_point(self, landmarks, index: int, img_width: int, img_height: int) -> Tuple[float, float]:
        """Extract a landmark point and convert to pixel coordinates."""
        try:
            landmark = landmarks.landmark[index]
            x = landmark.x * img_width
            y = landmark.y * img_height
            return (x, y)
        except (IndexError, AttributeError):
            return (0.0, 0.0)
    
    def _calculate_eye_aspect_ratio(self, landmarks, eye_indices: list, img_width: int, img_height: int) -> float:
        """Calculate Eye Aspect Ratio (EAR) with improved accuracy."""
        try:
            if len(eye_indices) < 6:
                return 0.0
            
            # Use 6 key points for EAR calculation
            key_indices = eye_indices[:6] if len(eye_indices) >= 6 else eye_indices
            points = [self._get_landmark_point(landmarks, idx, img_width, img_height) for idx in key_indices]
            
            if len(points) < 6:
                return 0.0
            
            # Calculate vertical distances (top to bottom)
            vertical_1 = np.linalg.norm(np.array(points[1]) - np.array(points[5]))
            vertical_2 = np.linalg.norm(np.array(points[2]) - np.array(points[4]))
            # Horizontal distance (left to right)
            horizontal = np.linalg.norm(np.array(points[0]) - np.array(points[3]))
            
            if horizontal == 0:
                return 0.0
            
            ear = (vertical_1 + vertical_2) / (2.0 * horizontal)
            return max(0.0, min(1.0, ear))  # Clamp to [0, 1]
        except Exception as e:
            logger.debug(f"EAR calculation error: {e}")
            return 0.0
    
    def _calculate_mouth_aspect_ratio(self, landmarks, img_width: int, img_height: int) -> float:
        """Calculate Mouth Aspect Ratio (MAR) with improved accuracy."""
        try:
            # Use more accurate mouth points
            left_corner = self._get_landmark_point(landmarks, 61, img_width, img_height)
            right_corner = self._get_landmark_point(landmarks, 291, img_width, img_height)
            top_lip = self._get_landmark_point(landmarks, 13, img_width, img_height)
            bottom_lip = self._get_landmark_point(landmarks, 14, img_width, img_height)
            
            vertical = np.linalg.norm(np.array(top_lip) - np.array(bottom_lip))
            horizontal = np.linalg.norm(np.array(left_corner) - np.array(right_corner))
            
            if horizontal == 0:
                return 0.0
            
            mar = vertical / horizontal
            return max(0.0, min(2.0, mar))  # Clamp to reasonable range
        except Exception as e:
            logger.debug(f"MAR calculation error: {e}")
            return 0.0
    
    def _calculate_eyebrow_position(self, landmarks, img_width: int, img_height: int) -> Tuple[float, float]:
        """Calculate eyebrow position relative to eyes (for surprise/fear/anger detection)."""
        try:
            left_eyebrow = self._get_landmark_point(landmarks, 70, img_width, img_height)
            right_eyebrow = self._get_landmark_point(landmarks, 336, img_width, img_height)
            left_eye_top = self._get_landmark_point(landmarks, 159, img_width, img_height)
            right_eye_top = self._get_landmark_point(landmarks, 386, img_width, img_height)
            
            left_raise = left_eyebrow[1] - left_eye_top[1]
            right_raise = right_eyebrow[1] - right_eye_top[1]
            
            avg_raise = (left_raise + right_raise) / 2.0
            
            # Normalize by face size
            face_width = abs(self._get_landmark_point(landmarks, 234, img_width, img_height)[0] - 
                           self._get_landmark_point(landmarks, 454, img_width, img_height)[0])
            if face_width > 0:
                normalized_raise = avg_raise / face_width
            else:
                normalized_raise = 0.0
                
            return normalized_raise, abs(left_raise - right_raise) / max(1.0, abs(avg_raise))  # asymmetry
        except Exception as e:
            logger.debug(f"Eyebrow calculation error: {e}")
            return 0.0, 0.0
    
    def _calculate_mouth_curvature(self, landmarks, img_width: int, img_height: int) -> Tuple[float, float]:
        """Calculate mouth curvature (positive = smile, negative = frown)."""
        try:
            left_corner = self._get_landmark_point(landmarks, 61, img_width, img_height)
            right_corner = self._get_landmark_point(landmarks, 291, img_width, img_height)
            mouth_center = self._get_landmark_point(landmarks, 13, img_width, img_height)
            
            # Calculate vertical position of corners relative to center
            corner_avg_y = (left_corner[1] + right_corner[1]) / 2.0
            curvature = mouth_center[1] - corner_avg_y  # Positive = smile, negative = frown
            
            # Normalize by mouth width
            mouth_width = abs(right_corner[0] - left_corner[0])
            if mouth_width > 0:
                normalized_curvature = curvature / mouth_width
            else:
                normalized_curvature = 0.0
            
            # Calculate mouth width relative to face
            face_width = abs(self._get_landmark_point(landmarks, 234, img_width, img_height)[0] - 
                           self._get_landmark_point(landmarks, 454, img_width, img_height)[0])
            if face_width > 0:
                mouth_ratio = mouth_width / face_width
            else:
                mouth_ratio = 0.0
                
            return normalized_curvature, mouth_ratio
        except Exception as e:
            logger.debug(f"Mouth curvature calculation error: {e}")
            return 0.0, 0.0
    
    def _detect_gaze_direction(self, landmarks, img_width: int, img_height: int) -> Tuple[str, float]:
        """
        Estimate gaze direction with confidence score.
        
        Returns:
            Tuple of (gaze_state, confidence)
        """
        try:
            # Get eye centers and nose tip
            left_eye_center = self._get_landmark_point(landmarks, self.LEFT_EYE_CENTER, img_width, img_height)
            right_eye_center = self._get_landmark_point(landmarks, self.RIGHT_EYE_CENTER, img_width, img_height)
            nose_tip = self._get_landmark_point(landmarks, self.NOSE_TIP, img_width, img_height)
            
            # Calculate face center
            face_center_x = (left_eye_center[0] + right_eye_center[0]) / 2
            face_center_y = (left_eye_center[1] + right_eye_center[1]) / 2
            
            # Calculate eye center position
            eye_center_x = (left_eye_center[0] + right_eye_center[0]) / 2
            eye_center_y = (left_eye_center[1] + right_eye_center[1]) / 2
            
            # Calculate offsets (normalized)
            horizontal_offset = (eye_center_x - face_center_x) / max(1.0, img_width)
            vertical_offset = (eye_center_y - face_center_y) / max(1.0, img_height)
            
            # Improved thresholds (more sensitive)
            HORIZONTAL_THRESHOLD = 0.015
            VERTICAL_THRESHOLD = 0.020
            
            # Calculate confidence based on offset magnitude
            offset_magnitude = np.sqrt(horizontal_offset**2 + vertical_offset**2)
            confidence = min(1.0, offset_magnitude * 10.0)  # Higher offset = higher confidence
            if confidence < 0.3:
                confidence = 0.3  # Minimum confidence
            
            # Determine gaze direction
            if abs(horizontal_offset) < HORIZONTAL_THRESHOLD and abs(vertical_offset) < VERTICAL_THRESHOLD:
                return "forward", max(0.5, confidence)
            elif vertical_offset > VERTICAL_THRESHOLD:
                return "down", confidence
            elif vertical_offset < -VERTICAL_THRESHOLD:
                return "up", confidence
            elif horizontal_offset < -HORIZONTAL_THRESHOLD:
                return "left", confidence
            elif horizontal_offset > HORIZONTAL_THRESHOLD:
                return "right", confidence
            else:
                return "forward", 0.5
                
        except Exception as e:
            logger.debug(f"Gaze detection error: {e}")
            return self.last_result.gaze_state, 0.3
    
    def _detect_expression_advanced(self, landmarks, img_width: int, img_height: int) -> Tuple[str, float, float]:
        """
        Advanced expression detection with confidence and intensity scoring.
        
        Returns:
            Tuple of (expression, confidence, intensity)
        """
        try:
            # Calculate all facial features
            left_ear = self._calculate_eye_aspect_ratio(landmarks, self.LEFT_EYE_INDICES, img_width, img_height)
            right_ear = self._calculate_eye_aspect_ratio(landmarks, self.RIGHT_EYE_INDICES, img_width, img_height)
            avg_ear = (left_ear + right_ear) / 2.0
            
            mar = self._calculate_mouth_aspect_ratio(landmarks, img_width, img_height)
            eyebrow_raise, eyebrow_asymmetry = self._calculate_eyebrow_position(landmarks, img_width, img_height)
            mouth_curvature, mouth_ratio = self._calculate_mouth_curvature(landmarks, img_width, img_height)
            
            # Calculate face size for normalization
            face_left = self._get_landmark_point(landmarks, 234, img_width, img_height)[0]
            face_right = self._get_landmark_point(landmarks, 454, img_width, img_height)[0]
            face_width = abs(face_right - face_left)
            
            # Expression scores (higher = more likely)
            expression_scores = {
                "neutral": 1.0,
                "happy": 0.0,
                "sad": 0.0,
                "fear": 0.0,
                "anger": 0.0,
                "surprise": 0.0,
                "disgust": 0.0
            }
            
            # Happy: raised mouth corners, wider mouth, normal eyes
            if mouth_curvature > 0.05 and mouth_ratio > 0.25:
                happy_score = min(1.0, (mouth_curvature * 10) + (mouth_ratio * 2))
                expression_scores["happy"] = happy_score
            
            # Sad: downturned mouth, lowered eyebrows, normal eyes
            if mouth_curvature < -0.03 and eyebrow_raise > 0.01:
                sad_score = min(1.0, abs(mouth_curvature * 15) + (eyebrow_raise * 10))
                expression_scores["sad"] = sad_score
            
            # Surprise: wide eyes, raised eyebrows, open mouth
            if avg_ear > 0.28 and eyebrow_raise < -0.02:
                surprise_score = min(1.0, ((avg_ear - 0.25) * 20) + abs(eyebrow_raise * 15))
                expression_scores["surprise"] = surprise_score
            
            # Fear: wide eyes, raised eyebrows, open mouth (more than surprise)
            if avg_ear > 0.28 and eyebrow_raise < -0.02 and mar > 0.35:
                fear_score = min(1.0, ((avg_ear - 0.25) * 15) + abs(eyebrow_raise * 12) + ((mar - 0.3) * 2))
                expression_scores["fear"] = fear_score
            
            # Anger: narrowed eyes, furrowed brows (lowered eyebrows), tense mouth
            if avg_ear < 0.20 and eyebrow_raise > 0.015:
                anger_score = min(1.0, ((0.25 - avg_ear) * 10) + (eyebrow_raise * 12))
                expression_scores["anger"] = anger_score
            
            # Disgust: narrowed eyes, downturned mouth, nose wrinkle (simplified)
            if avg_ear < 0.22 and mouth_curvature < -0.02:
                disgust_score = min(1.0, ((0.25 - avg_ear) * 8) + abs(mouth_curvature * 12))
                expression_scores["disgust"] = disgust_score
            
            # Find the expression with highest score
            best_expression = max(expression_scores, key=expression_scores.get)
            best_score = expression_scores[best_expression]
            
            # Calculate confidence (how much better is the best vs second best)
            sorted_scores = sorted(expression_scores.values(), reverse=True)
            if len(sorted_scores) > 1:
                score_diff = sorted_scores[0] - sorted_scores[1]
                confidence = min(1.0, 0.5 + (score_diff * 2))
            else:
                confidence = 0.5
            
            # Calculate intensity (how strong the emotion is)
            if best_expression == "neutral":
                intensity = 0.0
            else:
                intensity = min(1.0, best_score)
            
            return best_expression, confidence, intensity
            
        except Exception as e:
            logger.debug(f"Expression detection error: {e}")
            return self.last_result.expression, 0.5, 0.0
    
    def _calculate_engagement_level(self, gaze_state: str, gaze_confidence: float, 
                                   expression: str, expression_confidence: float, 
                                   intensity: float) -> float:
        """
        Calculate user engagement level based on gaze and expression.
        
        Returns:
            Engagement level from 0.0 (disengaged) to 1.0 (highly engaged)
        """
        engagement = 0.5  # Base engagement
        
        # Gaze contribution
        if gaze_state == "forward":
            engagement += 0.2 * gaze_confidence
        elif gaze_state in ["away", "down"]:
            engagement -= 0.3 * gaze_confidence
        else:
            engagement -= 0.1 * gaze_confidence
        
        # Expression contribution
        positive_expressions = {"happy", "surprise"}
        negative_expressions = {"sad", "fear", "anger", "disgust"}
        
        if expression in positive_expressions:
            engagement += 0.2 * intensity * expression_confidence
        elif expression in negative_expressions:
            engagement -= 0.2 * intensity * expression_confidence
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, engagement))
    
    def _apply_temporal_smoothing(self, expression: str, confidence: float) -> Tuple[str, float]:
        """Apply temporal smoothing to reduce flickering."""
        self.expression_history.append(expression)
        self.confidence_history.append(confidence)
        
        if len(self.expression_history) < 3:
            return expression, confidence
        
        # Use mode (most common) for expression
        from collections import Counter
        expression_counts = Counter(self.expression_history)
        smoothed_expression = expression_counts.most_common(1)[0][0]
        
        # Use average confidence
        smoothed_confidence = np.mean(list(self.confidence_history))
        
        return smoothed_expression, smoothed_confidence
    
    def detect(self, frame: np.ndarray) -> Dict[str, any]:
        """
        Detect gaze direction and micro-expression with confidence and intensity.
        
        Args:
            frame: BGR image frame (numpy array)
            
        Returns:
            Dictionary with:
            - gaze_state: str
            - micro_expression: str
            - expression_confidence: float
            - expression_intensity: float
            - gaze_confidence: float
            - engagement_level: float
        """
        if frame is None or frame.size == 0:
            return {
                "gaze_state": self.last_result.gaze_state,
                "micro_expression": self.last_result.expression,
                "expression_confidence": self.last_result.confidence,
                "expression_intensity": self.last_result.intensity,
                "gaze_confidence": self.last_result.gaze_confidence,
                "engagement_level": self.last_result.engagement_level
            }
        
        try:
            # Validate frame
            if len(frame.shape) != 3 or frame.shape[2] != 3:
                return {
                    "gaze_state": self.last_result.gaze_state,
                    "micro_expression": self.last_result.expression,
                    "expression_confidence": 0.3,
                    "expression_intensity": 0.0,
                    "gaze_confidence": 0.3,
                    "engagement_level": 0.3
                }
            
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame.shape[:2]
            
            if h == 0 or w == 0:
                return {
                    "gaze_state": self.last_result.gaze_state,
                    "micro_expression": self.last_result.expression,
                    "expression_confidence": 0.3,
                    "expression_intensity": 0.0,
                    "gaze_confidence": 0.3,
                    "engagement_level": 0.3
                }
            
            # Process frame
            results = self.face_mesh.process(rgb_frame)
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return {
                "gaze_state": self.last_result.gaze_state,
                "micro_expression": self.last_result.expression,
                "expression_confidence": 0.3,
                "expression_intensity": 0.0,
                "gaze_confidence": 0.3,
                "engagement_level": 0.3
            }
        
        if results.multi_face_landmarks:
            face_landmarks = results.multi_face_landmarks[0]
            
            # Detect gaze and expression
            gaze_state, gaze_confidence = self._detect_gaze_direction(face_landmarks, w, h)
            expression, expr_confidence, intensity = self._detect_expression_advanced(face_landmarks, w, h)
            
            # Apply temporal smoothing
            expression, expr_confidence = self._apply_temporal_smoothing(expression, expr_confidence)
            
            # Calculate engagement
            engagement = self._calculate_engagement_level(
                gaze_state, gaze_confidence, expression, expr_confidence, intensity
            )
            
            # Update last result
            self.last_result = EmotionResult(
                expression=expression,
                confidence=expr_confidence,
                intensity=intensity,
                gaze_state=gaze_state,
                gaze_confidence=gaze_confidence,
                engagement_level=engagement
            )
            
            return {
                "gaze_state": gaze_state,
                "micro_expression": expression,
                "expression_confidence": float(expr_confidence),
                "expression_intensity": float(intensity),
                "gaze_confidence": float(gaze_confidence),
                "engagement_level": float(engagement)
            }
        else:
            # No face detected
            return {
                "gaze_state": "away",
                "micro_expression": "neutral",
                "expression_confidence": 0.3,
                "expression_intensity": 0.0,
                "gaze_confidence": 0.3,
                "engagement_level": 0.2
            }
    
    def __del__(self):
        """Cleanup resources."""
        if hasattr(self, 'face_mesh'):
            self.face_mesh.close()
