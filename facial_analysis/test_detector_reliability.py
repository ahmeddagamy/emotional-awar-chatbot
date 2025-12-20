"""
Reliability and Accuracy Testing for Microexpression Detector

This script tests the detector's reliability, accuracy, and consistency.
"""

import cv2
import numpy as np
import time
import logging
from microexpression_detector import MicroexpressionDetector
from collections import Counter, defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DetectorTester:
    """Test suite for microexpression detector reliability."""
    
    def __init__(self):
        self.detector = MicroexpressionDetector()
        self.results = []
        
    def test_consistency(self, frame: np.ndarray, iterations: int = 10) -> Dict:
        """
        Test consistency by running detection multiple times on the same frame.
        
        Returns:
            Dictionary with consistency metrics
        """
        logger.info(f"Testing consistency with {iterations} iterations...")
        
        expressions = []
        gazes = []
        confidences = []
        intensities = []
        
        for _ in range(iterations):
            result = self.detector.detect(frame)
            expressions.append(result.get("micro_expression", "neutral"))
            gazes.append(result.get("gaze_state", "forward"))
            confidences.append(result.get("expression_confidence", 0.5))
            intensities.append(result.get("expression_intensity", 0.0))
        
        # Calculate consistency
        expr_consistency = len(set(expressions)) == 1
        gaze_consistency = len(set(gazes)) == 1
        
        # Calculate variance in confidence and intensity
        conf_variance = np.var(confidences)
        int_variance = np.var(intensities)
        
        return {
            "expression_consistent": expr_consistency,
            "gaze_consistent": gaze_consistency,
            "expression_mode": Counter(expressions).most_common(1)[0][0],
            "gaze_mode": Counter(gazes).most_common(1)[0][0],
            "confidence_variance": conf_variance,
            "intensity_variance": int_variance,
            "avg_confidence": np.mean(confidences),
            "avg_intensity": np.mean(intensities),
        }
    
    def test_performance(self, frame: np.ndarray, iterations: int = 100) -> Dict:
        """Test detection performance (speed)."""
        logger.info(f"Testing performance with {iterations} iterations...")
        
        times = []
        for _ in range(iterations):
            start = time.time()
            self.detector.detect(frame)
            elapsed = time.time() - start
            times.append(elapsed)
        
        return {
            "avg_time_ms": np.mean(times) * 1000,
            "min_time_ms": np.min(times) * 1000,
            "max_time_ms": np.max(times) * 1000,
            "fps": 1.0 / np.mean(times),
        }
    
    def test_edge_cases(self) -> Dict:
        """Test edge cases (empty frames, invalid inputs, etc.)."""
        logger.info("Testing edge cases...")
        
        results = {}
        
        # Empty frame
        empty_frame = np.array([])
        result = self.detector.detect(empty_frame)
        results["empty_frame"] = result.get("micro_expression") == "neutral"
        
        # None frame
        result = self.detector.detect(None)
        results["none_frame"] = result.get("micro_expression") == "neutral"
        
        # Invalid shape
        invalid_frame = np.zeros((100, 100), dtype=np.uint8)  # 2D instead of 3D
        result = self.detector.detect(invalid_frame)
        results["invalid_shape"] = "micro_expression" in result
        
        # Zero size
        zero_frame = np.zeros((0, 0, 3), dtype=np.uint8)
        result = self.detector.detect(zero_frame)
        results["zero_size"] = result.get("micro_expression") == "neutral"
        
        return results
    
    def test_confidence_scoring(self, frame: np.ndarray, iterations: int = 50) -> Dict:
        """Test that confidence scores are reasonable."""
        logger.info(f"Testing confidence scoring with {iterations} iterations...")
        
        confidences = []
        intensities = []
        
        for _ in range(iterations):
            result = self.detector.detect(frame)
            conf = result.get("expression_confidence", 0.5)
            intensity = result.get("expression_intensity", 0.0)
            confidences.append(conf)
            intensities.append(intensity)
        
        # Check ranges
        conf_in_range = all(0.0 <= c <= 1.0 for c in confidences)
        int_in_range = all(0.0 <= i <= 1.0 for i in intensities)
        
        return {
            "confidence_in_range": conf_in_range,
            "intensity_in_range": int_in_range,
            "avg_confidence": np.mean(confidences),
            "avg_intensity": np.mean(intensities),
            "confidence_std": np.std(confidences),
            "intensity_std": np.std(intensities),
        }
    
    def run_all_tests(self, test_frame: np.ndarray = None):
        """Run all tests and generate report."""
        logger.info("=" * 60)
        logger.info("Running Detector Reliability Tests")
        logger.info("=" * 60)
        
        # Create test frame if not provided
        if test_frame is None:
            test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            # Draw a simple face-like pattern for testing
            cv2.circle(test_frame, (320, 240), 100, (200, 180, 160), -1)
            cv2.circle(test_frame, (300, 220), 10, (0, 0, 0), -1)  # Left eye
            cv2.circle(test_frame, (340, 220), 10, (0, 0, 0), -1)  # Right eye
            cv2.ellipse(test_frame, (320, 260), (30, 15), 0, 0, 180, (0, 0, 0), 2)  # Mouth
        
        results = {}
        
        # Run tests
        logger.info("\n1. Consistency Test")
        results["consistency"] = self.test_consistency(test_frame, iterations=10)
        logger.info(f"   Expression consistent: {results['consistency']['expression_consistent']}")
        logger.info(f"   Gaze consistent: {results['consistency']['gaze_consistent']}")
        logger.info(f"   Avg confidence: {results['consistency']['avg_confidence']:.3f}")
        
        logger.info("\n2. Performance Test")
        results["performance"] = self.test_performance(test_frame, iterations=50)
        logger.info(f"   Avg time: {results['performance']['avg_time_ms']:.2f} ms")
        logger.info(f"   FPS: {results['performance']['fps']:.1f}")
        
        logger.info("\n3. Edge Cases Test")
        results["edge_cases"] = self.test_edge_cases()
        logger.info(f"   All edge cases handled: {all(results['edge_cases'].values())}")
        
        logger.info("\n4. Confidence Scoring Test")
        results["confidence"] = self.test_confidence_scoring(test_frame, iterations=30)
        logger.info(f"   Confidence in range: {results['confidence']['confidence_in_range']}")
        logger.info(f"   Intensity in range: {results['confidence']['intensity_in_range']}")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Test Summary")
        logger.info("=" * 60)
        
        all_passed = (
            results["consistency"]["expression_consistent"] or 
            results["consistency"]["confidence_variance"] < 0.1
        ) and all(results["edge_cases"].values()) and \
        results["confidence"]["confidence_in_range"] and \
        results["confidence"]["intensity_in_range"]
        
        logger.info(f"Overall: {'PASS' if all_passed else 'NEEDS IMPROVEMENT'}")
        logger.info(f"Performance: {results['performance']['fps']:.1f} FPS")
        logger.info(f"Reliability: {'Good' if all_passed else 'Needs attention'}")
        
        return results


if __name__ == "__main__":
    tester = DetectorTester()
    
    # Option 1: Test with dummy frame
    results = tester.run_all_tests()
    
    # Option 2: Test with webcam (if available)
    # cap = cv2.VideoCapture(0)
    # if cap.isOpened():
    #     ret, frame = cap.read()
    #     if ret:
    #         results = tester.run_all_tests(frame)
    #     cap.release()

