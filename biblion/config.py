"""Environment configuration — all settings read once at import time."""
import os

# Qdrant
QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY: str | None = os.environ.get("QDRANT_API_KEY")
COLLECTION_PREFIX: str = os.environ.get("QDRANT_COLLECTION_PREFIX", "biblion")
COLLECTION_NAME: str = f"{COLLECTION_PREFIX}_global"

# Embedding (Ollama-compatible)
EMBEDDING_URL: str = os.environ.get("EMBEDDING_URL", "http://localhost:11434")
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text:latest")

# Tuning
DEDUP_THRESHOLD: float = float(os.environ.get("DEDUP_THRESHOLD", "0.95"))
SEARCH_MIN_SCORE: float = float(os.environ.get("SEARCH_MIN_SCORE", "0.45"))
MAX_CANDIDATES: int = int(os.environ.get("MAX_CANDIDATES", "50"))
SIMILARITY_WEIGHT: float = float(os.environ.get("SIMILARITY_WEIGHT", "0.7"))
USAGE_WEIGHT: float = float(os.environ.get("USAGE_WEIGHT", "0.2"))
QUALITY_WEIGHT: float = float(os.environ.get("QUALITY_WEIGHT", "0.1"))
DEFAULT_QUALITY: float = float(os.environ.get("DEFAULT_QUALITY", "0.5"))

# Server
HOST: str = os.environ.get("HOST", "0.0.0.0")
PORT: int = int(os.environ.get("PORT", "18765"))
