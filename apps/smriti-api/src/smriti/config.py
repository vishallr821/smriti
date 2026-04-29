"""Application configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    supabase_url: str = Field(default="postgresql://postgres:password@localhost:5432/postgres")
    supabase_service_role_key: str = Field(default="service-role-key")
    supabase_anon_key: str = Field(default="anon-key")

    groq_api_key: str = Field(default="")
    ollama_base_url: str = Field(default="http://localhost:11434")
    demo_cache: bool = Field(default=False)
    debug_dp: bool = Field(default=False)

    mock_abha_url: str = Field(default="http://localhost:8001")
    mock_abha_signing_key: str = Field(default="mock-abha-signing-key")
    clinician_jwt_key: str = Field(default="clinician-jwt-key")

    system_salt: str = Field(default="system-salt")
    field_encryption_key: str = Field(default="")

    smriti_api_port: int = Field(default=8000)

    fhir_hospital_url: str = Field(default="http://localhost:8080/fhir")
    app_version: str = Field(default="0.1.0")
    git_commit: str = Field(default="unknown")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
