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

    # --- Phase 2: better retrieval (each step can be switched off to measure it) ---
    rag_hybrid: bool = True  # meaning (dense) + keyword (BM25) search, merged with RRF
    rag_rerank: bool = True  # a local cross-encoder re-scores the candidates
    rag_rewrite: bool = True  # follow-ups ("explain it again") -> standalone question
    rag_corrective: bool = True  # nothing relevant found -> rewrite the query once and search again
    rag_candidates: int = 20  # chunks fetched per search before reranking picks the best RAG_TOP_K
    rag_rrf_k: int = 60  # RRF constant: higher = ranks matter less
    rag_min_rerank_score: float = 0.02  # reranker relevance (0-1) below this = "not relevant"
    rag_history_turns: int = 3  # previous questions of the same chat used to rewrite follow-ups
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"  # ~80 MB, runs on CPU (ONNX)
    model_cache_dir: Path = BACKEND_DIR / "storage" / "models"  # downloaded once, reused

    # --- Phase 3: concept graph ---
    concept_extraction: bool = True  # extract concepts + prerequisites after a file is indexed
    concept_max_section_chars: int = 6000  # longer sections are sent in several parts
    concept_max_output_tokens: int = 1500
    # Two concepts with embedding similarity >= this are the SAME concept (auto-merged, name kept as alias)
    concept_merge_threshold: float = 0.90
    # >= this (but below the merge threshold): kept apart, flagged "possible duplicate" for the teacher
    concept_suggest_threshold: float = 0.80
    # "I don't understand X": below this similarity a concept isn't offered as a match
    learning_path_min_similarity: float = 0.35
    # Quizzes (3c): passages sent to the LLM per quiz, and how long each may be
    quiz_max_passages: int = 8
    quiz_passage_chars: int = 1500
    quiz_max_questions: int = 10
    quiz_max_output_tokens: int = 3000

    # --- Phase 4: routing, memory, practice ---
    # Embedding router: accept the nearest intent only if it is this similar AND this far ahead of the next one
    route_min_similarity: float = 0.45
    route_min_margin: float = 0.04
    route_max_output_tokens: int = 80
    weak_topic_score: int = 65  # quiz average below this = weak topic
    known_topic_score: int = 80  # quiz average at or above this = prerequisite marked "you know this"
    practice_questions: int = 3

    # --- MCP (Phase 4b) ---
    mcp_rate_limit_per_minute: int = 30  # tool calls per token (or per user for stdio/agent) per minute
    mcp_agent_max_steps: int = 4  # LLM calls the chat's tool-calling assistant may make for one message
    mcp_notes_dir: str | None = None  # a folder of your own notes, read through an external MCP server (dev only)

    # --- Tickets and knowledge base (Phase 5) ---
    faq_min_similarity: float = 0.80  # a support answer is used for a new question at least this similar (cosine)
    similar_ticket_min: float = 0.75  # "similar past tickets" shown to support at least this similar
    insights_group_similarity: float = 0.80  # teacher insights: questions this similar count as the same question
    ticket_on_no_answer: bool = True  # open a ticket when the course material has no answer (not only low confidence)
    insights_days: int = 30  # teacher insights look at this many days of questions

    # --- SQL agent (Phase 6) ---
    # A second Postgres login that can only SELECT, and only the rows row-level security lets through.
    # Created (and its password kept in step) by the backend at startup; see app/sql_agent/access.py.
    sql_agent_db_user: str = "lms_sql_reader"
    sql_agent_db_password: SecretStr = SecretStr("lms_sql_reader_password")
    sql_agent_max_attempts: int = 3  # SQL the model may write for one question (first try + self-corrections)
    sql_agent_max_rows: int = 200  # rows fetched from a query; more are cut off (and the answer says so)
    sql_agent_timeout_ms: int = 5000  # Postgres statement_timeout for agent queries
    sql_agent_answer_rows: int = 30  # rows shown to the LLM to write the answer (the UI gets them all)
    sql_agent_max_output_tokens: int = 700

    # --- Guardrails, evaluation, dashboards (Phase 7) ---
    guardrails: bool = True  # check chat messages for prompt injection and off-topic questions before answering
    # A message at least this similar (cosine) to a course topic or a known kind of request is on topic
    # without asking the LLM. Below it, a small LLM classifier decides (rules always run first).
    guard_on_topic_similarity: float = 0.40
    guard_max_output_tokens: int = 80
    # The model that grades answers in the eval. Empty = OPENAI_CHAT_MODEL (cheapest, but a model tends to
    # like its own answers: "self-preference bias"). Cost is estimated at the chat model's prices.
    eval_judge_model: str | None = None
    eval_max_output_tokens: int = 700
    eval_better_margin: float = 0.02  # a score must move more than this to count as better or worse

    # --- Langfuse (tracing) ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://us.cloud.langfuse.com"

    @field_validator("openai_base_url", "eval_judge_model", mode="before")
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
    def sql_agent_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.sql_agent_db_user}:{self.sql_agent_db_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
