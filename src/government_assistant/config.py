from dataclasses import dataclass
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=os.getenv("GSA_LOG_LEVEL", "DEBUG").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger().setLevel(os.getenv("GSA_LOG_LEVEL", "DEBUG").upper())


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("GSA_DATA_DIR", "data/curated"))
    storage_dir: Path = Path(os.getenv("GSA_STORAGE_DIR", "storage"))
    db_path: Path = Path(os.getenv("GSA_DB_PATH", "storage/database/assistant.sqlite3"))
    llm_provider: str = os.getenv("GSA_LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("GSA_LLM_MODEL", "qwen3:4b")
    ollama_url: str = os.getenv("GSA_OLLAMA_URL", "http://localhost:11434")
    embedding_model: str = os.getenv("GSA_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    embeddings_enabled: bool = os.getenv("GSA_EMBEDDINGS_ENABLED", "false").lower() == "true"
    stt_provider: str = os.getenv("GSA_STT_PROVIDER", "disabled")
    stt_model: str = os.getenv("GSA_STT_MODEL", "large-v3-turbo")
    chunk_size: int = int(os.getenv("GSA_CHUNK_SIZE", "900"))
    chunk_overlap: int = int(os.getenv("GSA_CHUNK_OVERLAP", "120"))
    top_k: int = int(os.getenv("GSA_RETRIEVAL_TOP_K", "5"))
    min_score: float = float(os.getenv("GSA_RETRIEVAL_MIN_SCORE", "0.05"))
    max_audio_mb: int = int(os.getenv("GSA_MAX_AUDIO_MB", "20"))
    log_level: str = os.getenv("GSA_LOG_LEVEL", "DEBUG").upper()


settings = Settings()
LANGUAGES = {
    "en": {"name": "English", "native_name": "English", "abstain": "I could not verify this information from the available scheme documents. Please consult an official source or try a more specific question."},
    "bn": {"name": "Bengali", "native_name": "বাংলা", "abstain": "উপলভ্য প্রকল্পের নথি থেকে এই তথ্য যাচাই করা যায়নি। অনুগ্রহ করে সরকারি উৎস দেখুন অথবা আরও নির্দিষ্ট প্রশ্ন করুন।"},
    "hi": {"name": "Hindi", "native_name": "हिन्दी", "abstain": "उपलब्ध योजना दस्तावेज़ों से इस जानकारी की पुष्टि नहीं हो सकी। कृपया आधिकारिक स्रोत देखें या अधिक विशिष्ट प्रश्न पूछें।"},
}
