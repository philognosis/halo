"""
Configuration for the Ontology-Driven Agentic Staffing System.
All settings are loaded from environment variables with sensible defaults.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Temporal
    TEMPORAL_HOST: str = "temporal:7233"
    TEMPORAL_NAMESPACE: str = "staffing"
    TEMPORAL_TASK_QUEUE: str = "staffing-queue"

    # PostgreSQL
    DATABASE_URL: str = "postgresql://staffing:staffing@postgres:5432/staffing"

    # Jena Fuseki
    FUSEKI_ENDPOINT: str = "http://fuseki:3030/staffing"

    @property
    def FUSEKI_SPARQL_ENDPOINT(self) -> str:
        return f"{self.FUSEKI_ENDPOINT}/sparql"

    @property
    def FUSEKI_UPDATE_ENDPOINT(self) -> str:
        return f"{self.FUSEKI_ENDPOINT}/update"

    # Ontology namespace
    STF_NAMESPACE: str = "http://enterprise.org/staffing/"

    # LLM
    LLM_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_API_KEY: str | None = None

    # ABox sync loop (Postgres → Jena projection)
    ABOX_SYNC_INTERVAL_SECONDS: int = 300

    # FastAPI service
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # SHACL / Ontology file paths (used by the ad-hoc validator)
    SHACL_SHAPES_PATH: str = "/app/ontology/shacl-shapes.ttl"
    ONTOLOGY_PATH: str = "/app/ontology/staffing-ontology.ttl"

    # Recommendation agent
    RECOMMENDATION_TOP_N: int = 5
    AGENT_EXPLAIN: bool = True


settings = Settings()
