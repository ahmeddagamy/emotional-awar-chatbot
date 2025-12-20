# Emotion-Aware Dental Chatbot System

## Overview

The system has been enhanced with advanced facial expression detection, emotion intensity weighting, and emotionally-aware response generation. The chatbot now adapts its responses based on the user's emotional state and engagement level.

## Key Enhancements

### 1. Advanced Microexpression Detection

**Features:**
- **Multi-frame temporal smoothing** - Reduces flickering and improves stability
- **Confidence scoring** - Each detection includes a confidence score (0.0 to 1.0)
- **Emotion intensity** - Measures how strong the detected emotion is (0.0 to 1.0)
- **Engagement level** - Calculates user engagement based on gaze and expression
- **Advanced facial analysis** - Uses multiple facial action units for more accurate detection

**Detected Emotions:**
- `neutral` - No strong emotion detected
- `happy` - Positive emotion (smile, raised mouth corners)
- `sad` - Negative emotion (downturned mouth, lowered eyebrows)
- `fear` - Anxiety or fear (wide eyes, raised eyebrows, open mouth)
- `anger` - Frustration or anger (narrowed eyes, furrowed brows)
- `surprise` - Surprise (wide eyes, raised eyebrows)
- `disgust` - Disgust (narrowed eyes, downturned mouth)

**Gaze States:**
- `forward` - Looking at camera (engaged)
- `away` - Looking away (disengaged)
- `down` - Looking down (possibly anxious or distracted)
- `left` / `right` - Looking to the side
- `up` - Looking up

### 2. Emotion Weight System

The system now calculates **emotion weights** that indicate:
- **Expression Confidence** (0.0-1.0): How certain the system is about the detected expression
- **Expression Intensity** (0.0-1.0): How strong the emotion is
- **Gaze Confidence** (0.0-1.0): How certain the gaze detection is
- **Engagement Level** (0.0-1.0): Overall user engagement score

These weights are used to:
- Filter out low-confidence detections
- Adapt response tone and content
- Provide appropriate emotional support

### 3. Emotionally-Aware Responses

The chatbot now provides responses that match the user's emotional state:

**For Sad Users (intensity > 0.5):**
- Warm, supportive tone
- Slower pace
- High reassurance
- Example: "I can sense you might be feeling down. I'm here to help make this process as comfortable as possible."

**For Anxious/Fearful Users (intensity > 0.4):**
- Calm, reassuring tone
- High support and reassurance
- Example: "I understand that dental visits can be anxiety-inducing. Let me reassure you - we'll go at your pace."

**For Angry Users (intensity > 0.4):**
- Steady, professional tone
- High support, moderate reassurance
- Example: "I sense some frustration. I'm here to help resolve any issues."

**For Happy Users (intensity > 0.5):**
- Positive, enthusiastic tone
- Normal pace
- Example: "Great to see you're in good spirits! I'm excited to help you."

### 4. Enhanced Actions

**New Actions:**
- `action_emotion_aware_response` - Adapts response tone based on emotion
- Enhanced `action_contextual_nudge` - Uses emotion weights for better timing

**Updated Slots:**
- `expression_confidence` - Confidence in expression detection
- `expression_intensity` - Strength of the emotion
- `emotion_weight` - Overall emotion weight for response adaptation
- `engagement_level` - User engagement score
- `emotion_tone_warmth` - Recommended warmth level
- `emotion_tone_pace` - Recommended response pace
- `emotion_tone_support` - Recommended support level

## API Changes

### Vision Server Endpoints

**GET /latest-signals** now returns:
```json
{
  "gaze_state": "forward",
  "micro_expression": "happy",
  "expression_confidence": 0.85,
  "expression_intensity": 0.72,
  "gaze_confidence": 0.78,
  "engagement_level": 0.82,
  "emotion_weight": 0.72,
  "sender_id": "user_123"
}
```

## Testing

### Reliability Test Suite

Run the test suite to verify accuracy and reliability:

```bash
cd facial_analysis
python test_detector_reliability.py
```

**Tests include:**
1. **Consistency Test** - Verifies consistent results on the same frame
2. **Performance Test** - Measures detection speed (target: >30 FPS)
3. **Edge Cases Test** - Tests handling of invalid inputs
4. **Confidence Scoring Test** - Verifies confidence scores are in valid ranges

### Expected Performance

- **Detection Speed**: 30-60 FPS (depending on hardware)
- **Confidence Range**: 0.3 to 1.0 (lower values indicate uncertainty)
- **Intensity Range**: 0.0 to 1.0 (0.0 = neutral, 1.0 = very strong emotion)
- **Consistency**: >90% consistent results on same frame

## Usage

### Basic Usage

The detector automatically provides emotion weights:

```python
from facial_analysis.microexpression_detector import MicroexpressionDetector
import cv2

detector = MicroexpressionDetector()
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if ret:
        result = detector.detect(frame)
        print(f"Expression: {result['micro_expression']}")
        print(f"Intensity: {result['expression_intensity']:.2f}")
        print(f"Confidence: {result['expression_confidence']:.2f}")
        print(f"Engagement: {result['engagement_level']:.2f}")
```

### Emotion-Aware Responses in Rasa

The Rasa actions automatically use emotion weights. To customize responses, check the slots:

```python
# In your Rasa action
intensity = tracker.get_slot("expression_intensity")
expression = tracker.get_slot("micro_expression")
engagement = tracker.get_slot("engagement_level")

if intensity > 0.5 and expression == "sad":
    # Provide extra support
    dispatcher.utter_message(text="I'm here to help...")
```

## Algorithm Details

### Expression Detection Algorithm

1. **Facial Feature Extraction:**
   - Eye Aspect Ratio (EAR) - Eye openness
   - Mouth Aspect Ratio (MAR) - Mouth openness
   - Eyebrow Position - Surprise/fear/anger indicator
   - Mouth Curvature - Smile/frown detection

2. **Expression Scoring:**
   - Each expression gets a score based on facial features
   - Scores are normalized and compared
   - Highest score determines the expression
   - Confidence = difference between top 2 scores

3. **Intensity Calculation:**
   - Based on how far facial features deviate from neutral
   - Normalized to 0.0-1.0 range
   - Higher intensity = stronger emotion

4. **Temporal Smoothing:**
   - Uses a sliding window (default: 5 frames)
   - Reduces flickering between expressions
   - Uses mode (most common) for stability

### Engagement Level Calculation

Engagement is calculated from:
- **Gaze direction** (forward = +engagement, away = -engagement)
- **Expression type** (positive = +engagement, negative = -engagement)
- **Intensity** (higher intensity = stronger impact)
- **Confidence** (higher confidence = more reliable)

## Configuration

### Detector Parameters

```python
detector = MicroexpressionDetector(
    smoothing_window=5  # Number of frames for temporal smoothing
)
```

### Thresholds

The system uses adaptive thresholds that work across different face sizes and lighting conditions. Key thresholds:

- **Expression Detection**: Confidence > 0.4 to act
- **Intensity Threshold**: > 0.3 for significant emotions
- **Gaze Thresholds**: 0.015 horizontal, 0.020 vertical (normalized)

## Best Practices

1. **Lighting**: Ensure good lighting for accurate detection
2. **Face Position**: User should face the camera for best results
3. **Confidence Filtering**: Only act on detections with confidence > 0.4
4. **Intensity Filtering**: Only respond to emotions with intensity > 0.3
5. **Temporal Smoothing**: Let the system stabilize over a few frames

## Troubleshooting

### Low Confidence Scores
- Check lighting conditions
- Ensure face is clearly visible
- Verify camera is working properly

### Inconsistent Detections
- Increase smoothing_window size
- Check for camera frame rate issues
- Verify MediaPipe is working correctly

### Performance Issues
- Reduce smoothing_window size
- Lower camera resolution
- Check CPU/GPU usage

## Future Enhancements

Potential improvements:
- Machine learning model for expression classification
- Multi-emotion detection (mixed emotions)
- Emotion history tracking
- Personalized emotion baselines
- Real-time emotion trend analysis

