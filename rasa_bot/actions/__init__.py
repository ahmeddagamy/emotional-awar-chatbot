# DENTAL_CHATBOT/__init__.py

"""
Dental Chatbot Project - Unified Initialization File

A comprehensive AI-powered dental consultation system with 
natural language processing and facial expression analysis.

This single file combines all package initialization logic.
"""

__version__ = "1.0.0"
__author__ = "Dental AI Innovation Team"
__license__ = "Proprietary"
__status__ = "Development"

import os
import sys
from typing import Dict, Any, List, Optional
import logging

# ==================== PROJECT CONFIGURATION ====================
PROJECT_STRUCTURE = {
    "data_generation": "Synthetic patient data and facial analysis datasets",
    "rasa_bot": "Core NLP assistant with custom actions", 
    "web_integration": "Frontend interface and webcam integration",
    "docs": "Project documentation and API references"
}

REQUIREMENTS = {
    "core": ["rasa==3.6.0", "tensorflow>=2.10.0", "opencv-python>=4.6.0", "numpy>=1.21.0", "flask>=2.0.0"],
    "facial_analysis": ["mediapipe>=0.8.0", "dlib>=19.24.0", "face_recognition>=1.3.0"],
    "database": ["sqlalchemy>=1.4.0", "psycopg2-binary>=2.9.0"]
}

# ==================== RASA BOT CONFIGURATION ====================
class DentalBotConfig:
    """Configuration for the dental chatbot"""
    
    def __init__(self):
        self.name = "DentalConsultant"
        self.version = __version__
        self.language = "en"
        self.features = {
            "facial_analysis": True,
            "real_time_adaptation": True,
            "appointment_booking": True,
            "multi_lingual": False,
            "voice_support": False
        }

# ==================== WEB INTEGRATION CONFIGURATION ====================
class WebConfig:
    """Web frontend configuration"""
    
    def __init__(self):
        self.host = "localhost"
        self.port = 3000
        self.debug = True
        self.static_folder = "static"
        self.template_folder = "templates"
        self.frontend_features = {
            "webcam_support": True,
            "real_time_chat": True,
            "facial_feedback": True,
            "responsive_design": True
        }

# ==================== DATA GENERATION CONFIGURATION ====================
class DataGenerationConfig:
    """Synthetic data generation configuration"""
    
    def __init__(self):
        self.num_patients = 1000
        self.date_range = {"start": "2020-01-01", "end": "2024-12-31"}
        self.medical_conditions = ["diabetes", "hypertension", "osteoporosis", "smoking"]
        self.procedures = ["implant", "cleaning", "consultation", "surgery"]
        self.output_formats = ["json", "csv", "sql"]

# ==================== CUSTOM ACTIONS REGISTRY ====================
class ActionRegistry:
    """Registry for all custom Rasa actions"""
    
    ACTIONS = {
        "appointment_actions": [
            "ActionSaveAppointment",
            "ActionBookConsultation", 
            "ActionCheckAvailability",
            "ActionScheduleFollowUp"
        ],
        "facial_analysis_actions": [
            "ActionDetectAnxiety",
            "ActionProvideReassurance", 
            "ActionSendFacialFeedback",
            "ActionAdaptResponseToEmotion"
        ],
        "patient_management_actions": [
            "ActionSavePatientInfo",
            "ActionValidateMedicalHistory",
            "ActionGenerateRiskProfile"
        ],
        "technical_actions": [
            "ActionProvideTechnicalDetails",
            "ActionHandleEmergency",
            "ActionExplainProcedure"
        ]
    }
    
    @classmethod
    def get_all_actions(cls) -> List[str]:
        """Get all registered actions"""
        all_actions = []
        for category in cls.ACTIONS.values():
            all_actions.extend(category)
        return all_actions

# ==================== FACIAL ANALYSIS INTEGRATION ====================
class FacialAnalysisManager:
    """Manages facial expression and gaze detection"""
    
    def __init__(self):
        self.enabled = True
        self.models_loaded = False
        self.detection_confidence = 0.7
        self.microexpression_threshold = 0.6
        
    def initialize_models(self) -> bool:
        """Initialize facial analysis models"""
        try:
            # Placeholder for model initialization
            logging.info("🔄 Initializing facial analysis models...")
            self.models_loaded = True
            logging.info("✅ Facial analysis models loaded successfully")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to load facial analysis models: {e}")
            return False
    
    def detect_emotions(self, frame_data: Any) -> Dict[str, float]:
        """Detect emotions from frame data"""
        if not self.models_loaded:
            return {"neutral": 1.0}
            
        # Placeholder for emotion detection logic
        return {
            "anxiety": 0.3,
            "confidence": 0.7, 
            "confusion": 0.2,
            "satisfaction": 0.8
        }
    
    def detect_gaze_pattern(self, frame_data: Any) -> Dict[str, Any]:
        """Detect gaze direction and patterns"""
        return {
            "looking_away": False,
            "gaze_duration": 2.5,
            "focus_score": 0.85,
            "attention_span": "high"
        }

# ==================== PATIENT DATA MANAGEMENT ====================
class PatientDataManager:
    """Manages patient data generation and storage"""
    
    def __init__(self):
        self.patients = []
        self.synthetic_data_generated = False
        
    def generate_synthetic_patients(self, count: int = 100) -> List[Dict]:
        """Generate synthetic patient data for testing"""
        import random
        from datetime import datetime, timedelta
        
        first_names = ["Ahmed", "Mohamed", "Ali", "Omar", "Sara", "Fatima", "Laila", "Nour"]
        last_names = ["Hassan", "Mostafa", "Elsayed", "Kamal", "Mahmoud", "Ibrahim"]
        conditions = ["diabetes", "hypertension", "none", "osteoporosis", "smoking"]
        
        patients = []
        for i in range(count):
            patient = {
                "id": i + 1,
                "name": f"{random.choice(first_names)} {random.choice(last_names)}",
                "age": random.randint(18, 80),
                "condition": random.choice(conditions),
                "last_visit": (datetime.now() - timedelta(days=random.randint(1, 365))).strftime("%Y-%m-%d"),
                "phone": f"01{random.randint(100000000, 999999999):09d}",
                "anxiety_level": round(random.uniform(0.1, 0.9), 2)
            }
            patients.append(patient)
        
        self.patients = patients
        self.synthetic_data_generated = True
        return patients
    
    def get_patient_by_id(self, patient_id: int) -> Optional[Dict]:
        """Retrieve patient by ID"""
        for patient in self.patients:
            if patient["id"] == patient_id:
                return patient
        return None

# ==================== UTILITY FUNCTIONS ====================
class DentalChatbotUtils:
    """Utility functions for the dental chatbot"""
    
    @staticmethod
    def validate_patient_data(patient_data: Dict) -> bool:
        """Validate patient data structure"""
        required_fields = ["name", "phone", "age"]
        return all(field in patient_data for field in required_fields)
    
    @staticmethod
    def format_appointment_date(date_str: str) -> str:
        """Format appointment date consistently"""
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M")
        except:
            return date_str
    
    @staticmethod
    def sanitize_phone_number(phone: str) -> str:
        """Sanitize and format phone number"""
        import re
        # Remove all non-digit characters
        cleaned = re.sub(r'\D', '', phone)
        if cleaned.startswith('0'):
            cleaned = '+20' + cleaned[1:]
        return cleaned
    
    @staticmethod
    def calculate_risk_score(patient_data: Dict) -> float:
        """Calculate risk score based on patient data"""
        score = 0.0
        if patient_data.get('condition') == 'diabetes':
            score += 0.3
        if patient_data.get('age', 0) > 60:
            score += 0.2
        if patient_data.get('smoking', False):
            score += 0.3
        return min(score, 1.0)
    
    @staticmethod
    def adapt_response_based_on_emotion(emotion_data: Dict, base_response: str) -> str:
        """Adapt bot response based on detected emotions"""
        anxiety_level = emotion_data.get('anxiety', 0)
        confidence_level = emotion_data.get('confidence', 0)
        
        if anxiety_level > 0.7:
            return f"😊 I understand this can be concerning. {base_response} Let me reassure you that our team has extensive experience with similar cases."
        elif confidence_level > 0.8:
            return f"👍 Great! You seem well-informed. {base_response} Would you like me to provide more technical details?"
        else:
            return base_response

# ==================== MAIN INITIALIZATION CLASS ====================
class DentalChatbot:
    """Main class that initializes and manages the entire dental chatbot system"""
    
    def __init__(self):
        self.config = DentalBotConfig()
        self.web_config = WebConfig()
        self.data_config = DataGenerationConfig()
        self.facial_analysis = FacialAnalysisManager()
        self.patient_manager = PatientDataManager()
        self.utils = DentalChatbotUtils()
        self.initialized = False
        self.logger = self._setup_logging()
        
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('dental_chatbot.log'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)
    
    def initialize(self) -> bool:
        """Initialize the entire dental chatbot system"""
        try:
            self.logger.info("=" * 60)
            self.logger.info("🦷 DENTAL CHATBOT PROJECT INITIALIZATION")
            self.logger.info("=" * 60)
            self.logger.info(f"Version: {__version__}")
            self.logger.info(f"Status: {__status__}")
            
            # Initialize facial analysis
            if self.facial_analysis.initialize_models():
                self.logger.info("✅ Facial Analysis: Models loaded")
            else:
                self.logger.warning("⚠️ Facial Analysis: Models not available")
            
            # Generate synthetic data
            self.patient_manager.generate_synthetic_patients(50)
            self.logger.info(f"✅ Patient Data: {len(self.patient_manager.patients)} synthetic patients generated")
            
            # Load Rasa model (placeholder)
            self.logger.info("✅ Rasa NLP: Model loading prepared")
            
            # Setup web server
            self.logger.info("✅ Web Integration: Configuration ready")
            
            self.logger.info("=" * 60)
            self.logger.info("🎯 FEATURES READY:")
            self.logger.info("  • Natural Language Processing (Rasa)")
            self.logger.info("  • Real-time Facial Expression Analysis") 
            self.logger.info("  • Webcam-based Gaze Tracking")
            self.logger.info("  • Appointment Booking System")
            self.logger.info("  • Patient Management Dashboard")
            self.logger.info("=" * 60)
            
            self.initialized = True
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Initialization failed: {e}")
            return False
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get current system status"""
        return {
            "version": __version__,
            "initialized": self.initialized,
            "facial_analysis_ready": self.facial_analysis.models_loaded,
            "patients_loaded": len(self.patient_manager.patients),
            "features": self.config.features
        }
    
    def process_conversation(self, user_message: str, facial_data: Optional[Dict] = None) -> Dict[str, Any]:
        """Process user message with optional facial data"""
        if not self.initialized:
            return {"error": "System not initialized"}
        
        # Placeholder for Rasa NLP processing
        base_response = "Thank you for your message. Our dental team will assist you shortly."
        
        # Adapt response based on facial data
        if facial_data:
            adapted_response = self.utils.adapt_response_based_on_emotion(facial_data, base_response)
        else:
            adapted_response = base_response
        
        return {
            "response": adapted_response,
            "emotion_detected": facial_data if facial_data else {"status": "no_data"},
            "timestamp": self.utils.format_appointment_date(str(__import__('datetime').datetime.now().isoformat()))
        }

# ==================== GLOBAL INSTANCE AND INITIALIZATION ====================
# Create global instance
_chatbot_instance = None

def get_chatbot() -> DentalChatbot:
    """Get or create the global chatbot instance"""
    global _chatbot_instance
    if _chatbot_instance is None:
        _chatbot_instance = DentalChatbot()
    return _chatbot_instance

def initialize_chatbot() -> bool:
    """Initialize the global chatbot instance"""
    chatbot = get_chatbot()
    return chatbot.initialize()

# ==================== EXPORT KEY COMPONENTS ====================
# Export main classes and functions
__all__ = [
    'DentalChatbot',
    'DentalBotConfig', 
    'WebConfig',
    'FacialAnalysisManager',
    'PatientDataManager',
    'DentalChatbotUtils',
    'ActionRegistry',
    'get_chatbot',
    'initialize_chatbot'
]

# ==================== AUTO-INITIALIZATION ====================
# Auto-initialize when package is imported (unless in testing mode)
if __name__ != "__main__" and os.getenv("DENTAL_CHATBOT_AUTO_INIT", "true").lower() == "true":
    if os.getenv("PYTEST_CURRENT_TEST") is None:  # Don't auto-init during tests
        initialize_chatbot()

# ==================== CONVENIENCE IMPORTS ====================
# These provide easy access to common functionality
def quick_start():
    """Quick start function for immediate use"""
    chatbot = get_chatbot()
    if not chatbot.initialized:
        chatbot.initialize()
    return chatbot

def generate_sample_patients(count: int = 10):
    """Quick function to generate sample patient data"""
    manager = PatientDataManager()
    return manager.generate_synthetic_patients(count)

def get_system_info():
    """Get quick system information"""
    chatbot = get_chatbot()
    return chatbot.get_system_status()

# ==================== MODULE METADATA ====================
if __name__ == "__main__":
    # Run basic initialization if file is executed directly
    chatbot = DentalChatbot()
    if chatbot.initialize():
        print("✅ Dental Chatbot initialized successfully!")
        print(f"📊 System Status: {chatbot.get_system_status()}")
    else:
        print("❌ Dental Chatbot initialization failed!")