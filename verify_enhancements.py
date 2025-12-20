"""Quick verification script for enhanced detector."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "facial_analysis"))

try:
    from microexpression_detector import MicroexpressionDetector, EmotionResult
    import numpy as np
    
    print("✓ Enhanced detector imports successfully")
    
    # Test initialization
    detector = MicroexpressionDetector()
    print("✓ Detector initialized successfully")
    
    # Test detection with dummy frame
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = detector.detect(dummy_frame)
    
    # Verify all required keys are present
    required_keys = ["gaze_state", "micro_expression", "expression_confidence", 
                     "expression_intensity", "gaze_confidence", "engagement_level"]
    
    all_present = all(key in result for key in required_keys)
    
    if all_present:
        print("✓ All emotion weight fields present")
        print(f"  Expression: {result['micro_expression']}")
        print(f"  Intensity: {result['expression_intensity']:.2f}")
        print(f"  Confidence: {result['expression_confidence']:.2f}")
        print(f"  Engagement: {result['engagement_level']:.2f}")
    else:
        print("✗ Missing required fields")
        sys.exit(1)
    
    print("\n✓ All enhancements verified successfully!")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

