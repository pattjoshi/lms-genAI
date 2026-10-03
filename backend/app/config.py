"""All settings come from the single `.env` file at the repo root.

Docker Compose reads the same file, so database passwords are defined once.
Change models, prices and limits in `.env` — never in code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_env: str = "dev"  # "dev" adds technical details to error responses
    app_timezone: str = "Asia/Kolkata"  # "today" for the daily budget uses this zone
    frontend_origin: str = "http://localhost:3000"

    # --- Postgres ---
    postgres_user: str = "lms"
    postgres_password: str = "lms_dev_password"
    postgres_db: str = "lms"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    # --- Qdrant / Neo4j ---
    qdrant_url: str = "http://localhost:6333"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "lms_neo4j_password"

    # --- OpenAI ---
    openai_api_key: SecretStr | None = None
    # Optional: an OpenAI-compatible endpoint (Azure, a proxy, a local server). Empty = api.openai.com
    openai_base_url: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    # Empty in .env = don't send temperature (needed for reasoning models).
    openai_temperature: float | None = 0.2
    # USD per 1M tokens. Check https://openai.com/api/pricing and update if they change.
    chat_price_input_per_1m: float = 0.15
    chat_price_output_per_1m: float = 0.60
    embedding_price_per_1m: float = 0.02

    # --- Error handling: retry, then stop ---
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3  # retries AFTER the first attempt -> max 4 calls
    llm_retry_base_delay_seconds: float = 1.0  # 1s, 2s, 4s ...
    llm_retry_max_delay_seconds: float = 20.0
    llm_max_output_tokens: int = 500
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_cooldown_seconds: float = 60.0

    # --- Cost guard ---
    daily_budget_usd: float = 1.0

    # --- Phase 1: upload pipeline ---
    upload_dir: Path = BACKEND_DIR / "storage" / "uploads"
    max_upload_mb: int = 10
    chunk_size: int = 1000  # characters (~250 tokens)
    chunk_overlap: int = 150  # characters shared by neighbouring chunks
    embedding_dim: int = 1536  # must match OPENAI_EMBEDDING_MODEL (text-embedding-3-small = 1536)
    embedding_batch_size: int = 64  # texts per embeddings API request
    qdrant_collection: str = "course_chunks"

    # --- Phase 1: RAG answering ---
    rag_top_k: int = 5  # chunks given to the LLM
    rag_min_score: float = 0.25  # below this cosine similarity a chunk counts as "not relevant"
    rag_max_output_tokens: int = 600

    # --- Langfuse (tracing) ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://us.cloud.langfuse.com"

    @field_validator("openai_base_url", mode="before")
    @classmethod
    def _empty_url_is_none(cls, value):
        return value or None

    @field_validator("openai_temperature", mode="before")
    @classmethod
    def _empty_temperature_is_none(cls, value):
        return None if value in ("", None) else value

    @field_validator("openai_api_key", "langfuse_public_key", "langfuse_secret_key", mode="before")
    @classmethod
    def _empty_or_placeholder_is_none(cls, value):
        # `.env.example` ships placeholders like "sk-..." — treat them as "not set".
        if value is None:
            return None
        text = str(value).strip()
        return None if text == "" or text.endswith("...") else text

    @property
    def database_url(self) -> str:
        # asyncpg (not psycopg) because psycopg's async mode does not work with the
        # default Windows event loop.
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
