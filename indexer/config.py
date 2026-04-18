import os

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_KEY_PREFIX: str = os.getenv("REDIS_KEY_PREFIX", "indexer")

EMBEDDING_URL: str = os.getenv("EMBEDDING_URL", "http://localhost:11434")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5")
EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "768"))

INDEXER_MAX_FILE_SIZE: int = int(os.getenv("INDEXER_MAX_FILE_SIZE", str(512 * 1024)))  # 512 KB
INDEXER_CHUNK_SIZE: int = int(os.getenv("INDEXER_CHUNK_SIZE", "50"))   # lines per chunk
INDEXER_CHUNK_OVERLAP: int = int(os.getenv("INDEXER_CHUNK_OVERLAP", "10"))  # overlap lines
INDEXER_TOP_K: int = int(os.getenv("INDEXER_TOP_K", "10"))
INDEXER_MIN_SCORE: float = float(os.getenv("INDEXER_MIN_SCORE", "0.35"))

# File extensions to index (empty = all non-binary)
INDEXER_EXTENSIONS: set[str] = set(
    os.getenv(
        "INDEXER_EXTENSIONS",
        ".py,.ts,.tsx,.js,.jsx,.go,.rs,.java,.c,.cpp,.h,.hpp,.cs,.rb,.php,.swift,.kt,.md,.txt,.yaml,.yml,.toml,.json,.sh",
    ).split(",")
)
