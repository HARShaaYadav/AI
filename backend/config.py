import os
from dotenv import load_dotenv

load_dotenv()

VAPI_API_KEY = os.getenv("VAPI_API_KEY", "")
VAPI_PUBLIC_KEY = os.getenv("VAPI_PUBLIC_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", ":memory:")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)
BACKEND_URL = os.getenv("BACKEND_URL", "https://aivoice.up.railway.app")
PRIMARY_LLM_MODEL = os.getenv("PRIMARY_LLM_MODEL", "gpt-5.1")
PRIMARY_LLM_TEMPERATURE = float(os.getenv("PRIMARY_LLM_TEMPERATURE", "0.4"))

USE_MEMORY_QDRANT = QDRANT_URL.strip() in ("", ":memory:")

LEGAL_COLLECTION = "legal_knowledge"
MEMORY_COLLECTION = "user_memory"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
VECTOR_SIZE = 384  # bge-small-en-v1.5 output size

SUPPORTED_LANGUAGES = {
    "hi": "Hindi",
    "en": "English",
    "ta": "Tamil",
    "bn": "Bengali",
    "mr": "Marathi",
    "te": "Telugu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "pa": "Punjabi",
    "ur": "Urdu",
}

VAPI_LANGUAGE_MAP = {
    "hi": "hi", "en": "en-IN", "ta": "ta", "bn": "bn",
    "mr": "mr", "te": "te", "gu": "gu", "kn": "kn",
    "pa": "pa", "ur": "ur",
}

EMERGENCY_KEYWORDS = [
    "help me", "hitting me", "emergency", "danger", "attack", "kill",
    "bachao", "maaro", "khatra", "madad karo", "help", "urgent",
    "abhi", "right now", "please help", "maar raha", "maar rahi",
    "jaan ka khatra", "threat", "assault",
]

VALID_DOC_TYPES = [
    "FIR",
    "Domestic Violence Complaint",
    "Harassment Complaint",
    "Labour Complaint",
    "Land Dispute Complaint",
    "Complaint Letter",
    "Consumer Complaint",
    "Cyber Crime Complaint",
]
